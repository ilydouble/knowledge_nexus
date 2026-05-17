from __future__ import annotations

from typing import Any

from nexus.models import IngestionJob, SyncRequest
from nexus.repository import InMemoryRepository
from nexus.services.ingestion import IngestionService


class FileEventHandler:
    INDEXABLE_EVENT_TYPES = {"create", "update", "modify", "rename"}

    def __init__(self, repository: InMemoryRepository) -> None:
        self.repository = repository
        self.ingestion = IngestionService(repository)

    def handle_events(self, events: list[dict[str, Any]], requested_by: str = "system") -> list[IngestionJob]:
        jobs: list[IngestionJob] = []
        for event in events:
            if event.get("type") not in self.INDEXABLE_EVENT_TYPES:
                continue
            uri = event.get("to") or event.get("uri")
            if not uri:
                continue
            jobs.append(self.ingestion.sync(SyncRequest(uri=uri, requested_by=requested_by)))
        return jobs

