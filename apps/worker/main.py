"""Worker — Discovery loop + candidate extraction batch processor.

Flow:
  SSE / scan  →  pending IngestionJob  →  CandidateExtractionPipeline.run()
                                           (creates candidate batch, NO Neo4j write)
                                        ↓
                               Pi-Agent / web UI reviews
                                        ↓
                               commit_candidate_batch() → Neo4j
"""

from __future__ import annotations

import asyncio
import json
import logging

from apps.api.factory import build_knowledge_os_store, build_repository
from core.cloudreve.client import CloudreveClient
from core.models import IngestionJob
from core.services.scanner import CloudreveScanner
from core.settings import Settings
from knowledge_os.application.extraction_pipeline import (
    CandidateExtractionPipeline,
    build_candidate_extraction_pipeline,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("apps.worker")


class Worker:
    """Three-loop worker: SSE discovery + periodic scan + candidate extraction."""

    PROCESSABLE_EVENTS = {"create", "update", "modify", "rename"}
    DELETE_EVENTS = {"delete", "remove", "trash"}

    def __init__(self) -> None:
        self.settings = Settings.from_env()
        self.repository = build_repository(self.settings)
        self.ko_store = build_knowledge_os_store(self.settings, self.repository)
        self.client = CloudreveClient()
        self.scanner = CloudreveScanner(self.client, self.repository)
        self._extraction_pipeline: CandidateExtractionPipeline | None = None
        self._neo4j_store = None
        self._milvus_store = None
        self._initialized = False

    # ── Lazy initialisation ───────────────────────────────────────────────────

    def _ensure_initialized(self) -> None:
        """Lazily build CandidateExtractionPipeline and storage backends for delete."""
        if self._initialized:
            return
        self._initialized = True

        # Candidate extraction pipeline (no Neo4j writes)
        self._extraction_pipeline = build_candidate_extraction_pipeline(
            self.settings, self.ko_store
        )
        if self._extraction_pipeline is None:
            logger.warning(
                "CandidateExtractionPipeline unavailable "
                "(missing LLM API key or Cloudreve token). "
                "Pending jobs will stay in queue until prerequisites are met."
            )

        # Neo4j — needed only for stale-file deletion
        if getattr(self.settings, "neo4j_uri", "") and getattr(self.settings, "neo4j_user", ""):
            try:
                from core.graph.neo4j_store import Neo4jGraphStore
                self._neo4j_store = Neo4jGraphStore(
                    uri=self.settings.neo4j_uri,
                    user=self.settings.neo4j_user,
                    password=self.settings.neo4j_password,
                )
            except Exception as exc:
                logger.warning("Neo4j unavailable: %s", exc)

        # Milvus — needed only for stale-file deletion
        if getattr(self.settings, "vector_backend", "none").lower() == "milvus" and getattr(self.settings, "milvus_host", ""):
            try:
                from core.services.embedding import DeterministicEmbeddingService
                from core.vector.milvus_store import MilvusVectorStore
                _emb = DeterministicEmbeddingService(dimensions=64)
                self._milvus_store = MilvusVectorStore(
                    host=self.settings.milvus_host,
                    port=self.settings.milvus_port,
                    dimensions=_emb.dimensions,
                )
            except Exception as exc:
                logger.warning("Milvus unavailable: %s", exc)

    # ── Job helpers ───────────────────────────────────────────────────────────

    def _create_job(self, uri: str, requested_by: str = "worker") -> IngestionJob:
        job = IngestionJob(uri=uri, requested_by=requested_by, status="pending", stage="queued")
        return self.repository.add_job(job)

    def _mark_running(self, job_id: str) -> IngestionJob:
        job = self.repository.get_job(job_id)
        job.status = "running"
        return self.repository.update_job(job)

    def _mark_succeeded(self, job_id: str) -> IngestionJob:
        job = self.repository.get_job(job_id)
        job.status = "succeeded"
        return self.repository.update_job(job)

    def _mark_failed(self, job_id: str, error: str, stage: str = "extract", error_code: str | None = None) -> IngestionJob:
        job = self.repository.get_job(job_id)
        job.status = "failed"
        job.stage = stage
        return self.repository.update_job(job)

    def _mark_skipped(self, job_id: str, reason: str) -> IngestionJob:
        job = self.repository.get_job(job_id)
        job.status = "skipped"
        job.stage = reason
        return self.repository.update_job(job)

    # ── Core processing ───────────────────────────────────────────────────────

    async def _process_one(self, job_id: str, uri: str) -> None:
        """Run one pending job through CandidateExtractionPipeline.

        Produces a candidate batch — does NOT write to Neo4j.
        Pi-Agent or the web UI reviews and calls commit_candidate_batch().
        """
        self._ensure_initialized()
        if self._extraction_pipeline is None:
            logger.warning("Extraction pipeline unavailable, leaving job %s pending", job_id)
            return

        self._mark_running(job_id)
        try:
            batch = await asyncio.to_thread(
                self._extraction_pipeline.run,
                uri,
                requested_by="worker",
            )
            self._mark_succeeded(job_id)
            item_count = len(batch.items) if hasattr(batch, "items") else "?"
            logger.info("Candidate batch %s created for %s (%s items, pending review)", batch.id, uri, item_count)
        except Exception as exc:
            self._mark_failed(job_id, str(exc), stage="extract", error_code="extraction_error")
            logger.error("Extraction failed for %s: %s", uri, exc)

    def _sync_delete(self, uri: str) -> None:
        """Synchronous multi-store delete — used as scanner delete_fn callback."""
        for store, method in [
            (self._neo4j_store, "delete_file"),
            (self._milvus_store, "delete_chunks_by_uri"),
        ]:
            if store is not None:
                try:
                    getattr(store, method)(uri)
                except Exception as exc:
                    logger.warning("%s.%s(%s) failed: %s", type(store).__name__, method, uri, exc)
        try:
            self.repository.delete_document(uri)
        except Exception as exc:
            logger.warning("repository.delete_document(%s) failed: %s", uri, exc)

    async def _handle_delete(self, uri: str) -> None:
        """Delete all knowledge data for a removed file (runs sync delete in thread)."""
        self._ensure_initialized()
        await asyncio.to_thread(self._sync_delete, uri)

    # ── Event + scan loops ────────────────────────────────────────────────────

    async def process_event(self, event: dict) -> None:
        """Queue a Cloudreve file event as a pending ingestion job."""
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

        if event_type in self.DELETE_EVENTS:
            await self._handle_delete(uri)
            return

        existing = [j for j in self.repository.list_jobs() if j.uri == uri and j.status in ("pending", "running")]
        if existing:
            logger.debug("Job already queued for %s, skipping duplicate", uri)
            return

        self._create_job(uri, requested_by="worker")
        logger.info("Queued pending job for %s (event: %s)", uri, event_type)

    async def process_pending_loop(self, poll_interval_seconds: float = 30.0, batch_size: int = 3) -> None:
        """Pick up pending jobs and produce candidate batches (no direct Neo4j writes)."""
        logger.info("Batch processor starting (poll=%.0fs, batch_size=%d)", poll_interval_seconds, batch_size)
        while True:
            pending = [j for j in self.repository.list_jobs() if j.status == "pending"]
            if pending:
                batch = pending[:batch_size]
                logger.info("Processing batch of %d job(s) (%d total pending)", len(batch), len(pending))
                for job in batch:
                    await self._process_one(job.id, job.uri)
            await asyncio.sleep(poll_interval_seconds)

    async def run(self) -> None:
        """Listen for Cloudreve SSE events and queue file-change events."""
        logger.info("SSE listener starting (cloudreve_base_url=%s)", getattr(self.settings, "cloudreve_base_url", "?"))
        async for event in self.client.iter_file_events(client_id=self.settings.cloudreve_client_id):
            event_type = event.get("type", "data")
            if event_type == "connected":
                logger.info("SSE connection established")
                continue
            if event_type in ("subscribed", "resumed"):
                continue
            if event_type == "error":
                logger.error("SSE error: %s", event.get("error"))
                continue
            if event_type not in ("data", "event"):
                continue
            raw = event.get("raw", "")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Ignoring non-JSON SSE payload: %s", raw)
                continue
            for evt in (payload if isinstance(payload, list) else [payload]):
                await self.process_event(evt)

    async def scan_loop(self, interval_seconds: float = 600.0) -> None:
        """Periodically walk Cloudreve, queue new files, and clean up stale data."""
        logger.info("Periodic scanner starting (interval: %.0fs)", interval_seconds)
        while True:
            try:
                self._ensure_initialized()
                result = await self.scanner.scan(
                    requested_by="periodic-scanner",
                    delete_fn=self._sync_delete,   # sync; scanner wraps in to_thread
                )
                logger.info(
                    "Periodic scan finished: %d found, %d queued, %d stale deleted",
                    result.files_found, result.files_queued, result.files_deleted,
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
        """Three concurrent loops:

        Loop 1 – SSE listener       : queues pending jobs on Cloudreve events.
        Loop 2 – Periodic scanner   : discovers files missed by SSE, cleans stale data.
        Loop 3 – Batch processor    : runs CandidateExtractionPipeline on pending jobs.
                                      Results are candidate batches awaiting review —
                                      nothing is written to Neo4j automatically.

        When ENABLE_PERIODIC_SYNC is false, all three loops are skipped and the
        worker idles, so a cleared graph stays empty until the user explicitly
        extracts/commits again.
        """
        if not self.settings.enable_periodic_sync:
            logger.info(
                "Periodic sync disabled (ENABLE_PERIODIC_SYNC=false); "
                "worker idling — no SSE listener, scan, or extraction will run."
            )
            while True:
                await asyncio.sleep(3600)

        async def _sse_loop() -> None:
            while True:
                try:
                    await self.run()
                    logger.warning("Cloudreve event stream closed; reconnecting in %.1fs", reconnect_delay_seconds)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    logger.error("Worker event loop failed: %s; reconnecting in %.1fs", exc, reconnect_delay_seconds)
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
