"""Worker - Process Cloudreve file events through semantic pipeline."""

from __future__ import annotations

import asyncio
import json
import logging

from nexus.cloudreve.client import CloudreveClient
from nexus.app_factory import build_repository
from nexus.services.events import FileEventHandler
from nexus.services.ingestion import IngestionService
from nexus.services.pipeline import SemanticPipeline
from nexus.services.scanner import CloudreveScanner
from nexus.settings import Settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nexus.worker")


class Worker:
    """Process Cloudreve file events through semantic pipeline."""
    
    # Event types that trigger processing (queue a job)
    PROCESSABLE_EVENTS = {"create", "update", "modify", "rename"}
    # Event types that trigger immediate deletion (no job queue)
    DELETE_EVENTS = {"delete", "remove", "trash"}
    
    def __init__(self) -> None:
        self.settings = Settings.from_env()
        self.repository = build_repository(self.settings)
        self.ingestion = IngestionService(self.repository)
        self.handler = FileEventHandler(self.repository)
        self.client = CloudreveClient()
        self.scanner = CloudreveScanner(self.client, self.repository)
        self.pipeline: SemanticPipeline | None = None
        self._initialized = False
    
    def _ensure_pipeline(self) -> None:
        """Lazily initialize the pipeline."""
        if not self._initialized:
            try:
                self.pipeline = SemanticPipeline(
                    cloudreve_token=None,
                    settings=self.settings,
                    repository=self.repository,
                    enable_neo4j=bool(getattr(self.settings, "neo4j_uri", "")),
                    enable_milvus=bool(getattr(self.settings, "milvus_host", "")),
                )
            except Exception as e:
                logger.warning(f"Failed to initialize pipeline: {e}")
                self.pipeline = None
            self._initialized = True
    
    async def process_event(self, event: dict) -> None:
        """Queue a file event for later batch processing.

        We deliberately do NOT run the semantic pipeline here.  Immediately
        analysing every upload would:
        - Fire LLM calls for every user action in real time
        - Create uncontrolled concurrency with no back-pressure
        - Duplicate work already picked up by the periodic scanner

        Instead we just create a *pending* ingestion job.  The
        ``process_pending_loop`` picks it up on its next tick.
        """
        event_type = event.get("type", "")

        if event_type not in self.PROCESSABLE_EVENTS and event_type not in self.DELETE_EVENTS:
            logger.debug("Ignoring event type: %s", event_type)
            return

        uri = event.get("to") or event.get("uri")
        if not uri:
            logger.warning("No URI in event: %s", event)
            return

        if not uri.startswith("cloudreve://"):
            uri = f"cloudreve://my{uri if uri.startswith('/') else '/' + uri}"

        # Delete events: clean up immediately, no job queue
        if event_type in self.DELETE_EVENTS:
            await self._handle_delete(uri)
            return

        # Deduplicate: skip if a pending/running job already exists for this URI
        existing = [
            j for j in self.repository.list_jobs()
            if j.uri == uri and j.status in ("pending", "running")
        ]
        if existing:
            logger.debug("Job already queued for %s, skipping SSE duplicate", uri)
            return

        self.handler.handle_events([event])
        logger.info("Queued pending job for %s (event: %s)", uri, event_type)

    async def _process_one(self, job_id: str, uri: str) -> None:
        """Run a single pending job through the semantic pipeline."""
        self._ensure_pipeline()
        if self.pipeline is None:
            logger.warning("Pipeline not available, skipping %s", uri)
            return

        self.ingestion.mark_running(job_id)
        self.ingestion.mark_stage(job_id, "download")

        try:
            result = await asyncio.to_thread(
                self.pipeline.process_file,
                uri,
                "batch-processor",
            )
            if result.skipped:
                self.ingestion.mark_skipped(job_id, result.skip_reason or "unsupported file type")
                logger.info("Gate skipped %s: %s", uri, result.skip_reason)
            elif result.success:
                self.ingestion.mark_succeeded(job_id)
                logger.info(
                    "Processed %s: entities=%d relations=%d chunks=%d time=%dms",
                    uri,
                    result.entities_count,
                    result.relations_count,
                    result.chunks_count,
                    result.processing_time_ms,
                )
            else:
                self.ingestion.mark_failed(
                    job_id,
                    result.error or "processing failed",
                    stage=result.stage or "download",
                    error_code=result.error_code,
                )
                logger.error("Failed to process %s: %s", uri, result.error)
        except Exception as exc:
            self.ingestion.mark_failed(job_id, str(exc), stage="download", error_code="worker_exception")
            logger.error("Error processing %s: %s", uri, exc)

    async def _handle_delete(self, uri: str) -> None:
        """Delete all knowledge data for *uri* across every storage backend."""
        self._ensure_pipeline()
        if self.pipeline is None:
            logger.warning("Pipeline not available, cannot delete %s", uri)
            return
        try:
            await asyncio.to_thread(self.pipeline.delete_file, uri)
        except Exception as exc:
            logger.error("Error deleting knowledge for %s: %s", uri, exc)

    async def process_pending_loop(
        self,
        poll_interval_seconds: float = 30.0,
        batch_size: int = 3,
    ) -> None:
        """Continuously consume pending ingestion jobs in small batches.

        Args:
            poll_interval_seconds: How often to check for new pending jobs.
                Defaults to 30 s so the loop is responsive without hammering
                the repository.
            batch_size: Maximum jobs to process per tick.  Keeps LLM API
                concurrency bounded; adjust to taste.
        """
        logger.info(
            "Batch processor starting (poll=%.0fs, batch_size=%d)",
            poll_interval_seconds,
            batch_size,
        )
        while True:
            pending = [j for j in self.repository.list_jobs() if j.status == "pending"]
            if pending:
                batch = pending[:batch_size]
                logger.info(
                    "Processing batch of %d job(s) (%d total pending)",
                    len(batch),
                    len(pending),
                )
                for job in batch:
                    await self._process_one(job.id, job.uri)
            await asyncio.sleep(poll_interval_seconds)
    
    async def run(self) -> None:
        """Run the worker, listening for Cloudreve events."""
        logger.info(f"Starting worker, connecting to {getattr(self.settings, 'cloudreve_base_url', 'Cloudreve')}")
        logger.info(f"Client ID: {self.settings.cloudreve_client_id}")
        
        async for event in self.client.iter_file_events(
            client_id=self.settings.cloudreve_client_id
        ):
            event_type = event.get("type", "data")
            
            if event_type == "connected":
                logger.info("SSE connection established")
                continue
            
            if event_type in ("subscribed", "resumed"):
                logger.info(f"SSE subscription: {event_type}")
                continue
            
            if event_type == "error":
                logger.error(f"SSE error: {event.get('error')}")
                continue
            
            if event_type not in ("data", "event"):
                continue
            
            # Parse event data
            raw = event.get("raw", "")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug(f"Ignoring non-JSON event: {raw}")
                continue
            
            # Handle single event or batch
            events = payload if isinstance(payload, list) else [payload]
            
            for evt in events:
                # Process through pipeline
                await self.process_event(evt)

    async def scan_loop(self, interval_seconds: float = 600.0) -> None:
        """Periodically scan Cloudreve for new files and queue them.

        Runs an initial scan immediately on startup, then repeats every
        *interval_seconds* (default 10 minutes).  Errors are logged and
        swallowed so the loop never dies from a transient failure.
        """
        logger.info("Periodic scanner starting (interval: %.0fs)", interval_seconds)
        while True:
            try:
                self._ensure_pipeline()
                delete_fn = self.pipeline.delete_file if self.pipeline else None
                result = await self.scanner.scan(
                    requested_by="periodic-scanner",
                    delete_fn=delete_fn,
                )
                logger.info(
                    "Periodic scan finished: %d found, %d queued, %d stale deleted",
                    result.files_found,
                    result.files_queued,
                    result.files_deleted,
                )
            except Exception as exc:
                logger.error("Periodic scan error: %s", exc)
            await asyncio.sleep(interval_seconds)

    async def run_forever(
        self,
        reconnect_delay_seconds: float = 5.0,
        scan_interval_seconds: float = 600.0,
        poll_interval_seconds: float = 30.0,
        batch_size: int = 3,
    ) -> None:
        """Keep the worker alive with three concurrent loops.

        Loop 1 – SSE listener
            Stays connected to Cloudreve's event stream.  On upload/rename
            events it creates a *pending* job (no immediate LLM call).
            Reconnects automatically on disconnect.

        Loop 2 – Periodic scanner  (default: every 10 min)
            Walks the entire Cloudreve drive and creates pending jobs for any
            file that has no existing job or document.  This is the primary
            discovery mechanism and catches files missed by SSE.

        Loop 3 – Batch processor  (default: every 30 s, up to 3 jobs/tick)
            Picks up pending jobs and runs them through the semantic pipeline
            (download → parse → LLM extract → store).  Processing is decoupled
            from discovery, giving us natural back-pressure and rate control.
        """

        async def _sse_loop() -> None:
            while True:
                try:
                    await self.run()
                    logger.warning(
                        "Cloudreve event stream closed; reconnecting in %.1fs",
                        reconnect_delay_seconds,
                    )
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    logger.error(
                        "Worker event loop failed: %s; reconnecting in %.1fs",
                        exc,
                        reconnect_delay_seconds,
                    )
                await asyncio.sleep(reconnect_delay_seconds)

        await asyncio.gather(
            _sse_loop(),
            self.scan_loop(scan_interval_seconds),
            self.process_pending_loop(poll_interval_seconds, batch_size),
        )


async def watch_cloudreve_events() -> None:
    """Legacy function for backward compatibility."""
    worker = Worker()
    await worker.run()


def main() -> None:
    """Main entry point."""
    worker = Worker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
