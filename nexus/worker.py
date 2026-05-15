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
from nexus.settings import Settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nexus.worker")


class Worker:
    """Process Cloudreve file events through semantic pipeline."""
    
    # Event types that trigger processing
    PROCESSABLE_EVENTS = {"create", "update", "modify", "rename"}
    
    def __init__(self) -> None:
        self.settings = Settings.from_env()
        self.repository = build_repository(self.settings)
        self.ingestion = IngestionService(self.repository)
        self.handler = FileEventHandler(self.repository)
        self.client = CloudreveClient(token=self.settings.cloudreve_token)
        self.pipeline: SemanticPipeline | None = None
        self._initialized = False
    
    def _ensure_pipeline(self) -> None:
        """Lazily initialize the pipeline."""
        if not self._initialized:
            try:
                self.pipeline = SemanticPipeline(
                    cloudreve_token=self.settings.cloudreve_token,
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
        """Process a single file event."""
        event_type = event.get("type", "")
        
        if event_type not in self.PROCESSABLE_EVENTS:
            logger.debug(f"Ignoring event type: {event_type}")
            return
        
        # Get file URI from event
        uri = event.get("to") or event.get("uri")
        if not uri:
            logger.warning(f"No URI in event: {event}")
            return
        
        # Normalize URI
        if not uri.startswith("cloudreve://"):
            uri = f"cloudreve://my{uri if uri.startswith('/') else '/' + uri}"
        
        logger.info(f"Processing file: {uri} (event: {event_type})")
        
        # Ensure pipeline is initialized
        self._ensure_pipeline()
        
        if self.pipeline is None:
            logger.warning("Pipeline not available, skipping processing")
            return
        
        jobs = self.handler.handle_events([event])
        job = jobs[0] if jobs else None
        if job:
            self.ingestion.mark_running(job.id)

        try:
            # Process file through pipeline
            result = self.pipeline.process_file(
                uri=uri,
                requested_by="worker",
            )
            
            if result.success:
                if job:
                    self.ingestion.mark_succeeded(job.id)
                logger.info(
                    f"Successfully processed {uri}: "
                    f"entities={result.entities_count}, "
                    f"relations={result.relations_count}, "
                    f"chunks={result.chunks_count}, "
                    f"time={result.processing_time_ms}ms"
                )
            else:
                if job:
                    self.ingestion.mark_failed(job.id, result.error or "processing failed")
                logger.error(f"Failed to process {uri}: {result.error}")
        
        except Exception as e:
            if job:
                self.ingestion.mark_failed(job.id, str(e))
            logger.error(f"Error processing {uri}: {e}")
    
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


async def watch_cloudreve_events() -> None:
    """Legacy function for backward compatibility."""
    worker = Worker()
    await worker.run()


def main() -> None:
    """Main entry point."""
    worker = Worker()
    asyncio.run(worker.run())


if __name__ == "__main__":
    main()
