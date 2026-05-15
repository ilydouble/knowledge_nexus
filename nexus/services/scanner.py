"""CloudreveScanner – discover all files in Cloudreve and queue them for ingestion.

Design rationale
----------------
The SSE-based worker only sees events that occur *while* it is connected.
Files that existed before the worker started, or files uploaded during a
reconnection gap, are silently missed.

The ``CloudreveScanner`` closes that gap by walking the Cloudreve directory
tree on demand (or on a timer).  For every file it discovers that has no
corresponding ingestion job or semantic document, it creates a ``pending``
ingestion job so the worker pipeline can pick it up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nexus.cloudreve.client import CloudreveClient, CloudreveError
from nexus.models import SyncRequest
from nexus.repositories.base import NexusRepository
from nexus.services.ingestion import IngestionService

logger = logging.getLogger("nexus.scanner")


@dataclass
class ScanResult:
    """State snapshot of the most recent scan run."""

    status: str = "idle"  # idle | scanning | done | error
    started_at: datetime | None = None
    finished_at: datetime | None = None
    files_found: int = 0
    files_queued: int = 0
    error: str | None = None
    discovered_uris: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "files_found": self.files_found,
            "files_queued": self.files_queued,
            "error": self.error,
        }


class CloudreveScanner:
    """Walk the Cloudreve directory tree and submit new files for ingestion.

    Thread/task safety
    ------------------
    ``scan()`` is a coroutine.  A guard flag (``_scanning``) prevents
    concurrent runs; a second call while a scan is in progress returns the
    current ``ScanResult`` immediately.
    """

    def __init__(self, client: CloudreveClient, repository: NexusRepository) -> None:
        self.client = client
        self.repository = repository
        self.ingestion = IngestionService(repository)
        self._last_result: ScanResult = ScanResult()
        self._scanning = False

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    def last_result(self) -> ScanResult:
        return self._last_result

    async def scan(
        self,
        root_uri: str = "cloudreve://my",
        requested_by: str = "scanner",
    ) -> ScanResult:
        """Scan *root_uri* recursively and queue newly-discovered files.

        Returns immediately (with the in-progress result) if a scan is already
        running.
        """
        if self._scanning:
            return self._last_result

        self._scanning = True
        result = ScanResult(status="scanning", started_at=datetime.now(UTC))
        self._last_result = result

        try:
            discovered: list[str] = []
            await self._walk(root_uri, discovered)
            result.files_found = len(discovered)
            result.discovered_uris = discovered

            # Determine which URIs are already known to the system
            known_uris: set[str] = set()
            known_uris.update(job.uri for job in self.repository.list_jobs())
            known_uris.update(doc.uri for doc in self.repository.list_documents())

            queued = 0
            for uri in discovered:
                if uri not in known_uris:
                    self.ingestion.sync(SyncRequest(uri=uri, requested_by=requested_by))
                    queued += 1

            result.files_queued = queued
            result.status = "done"
            result.finished_at = datetime.now(UTC)
            logger.info(
                "Scan complete: %d files found, %d new URIs queued for ingestion",
                result.files_found,
                result.files_queued,
            )

        except Exception as exc:
            result.status = "error"
            result.error = str(exc)
            result.finished_at = datetime.now(UTC)
            logger.error("Scan failed: %s", exc)

        finally:
            self._scanning = False

        return result

    async def _walk(self, uri: str, collected: list[str]) -> None:
        """Recursively list *uri* and append file URIs to *collected*."""
        try:
            items = await self.client.list_files(uri)
        except CloudreveError as exc:
            logger.warning("Cannot list %s: %s", uri, exc)
            return

        if not items:
            return

        # Cloudreve v4 returns {"objects": [...]} inside the unwrapped data.
        # Guard against other shapes (list, plain items key, etc.).
        if isinstance(items, dict):
            objects = items.get("objects") or items.get("items") or []
        elif isinstance(items, list):
            objects = items
        else:
            return

        for obj in objects:
            obj_uri: str = obj.get("uri") or obj.get("path") or ""
            if not obj_uri:
                continue
            is_dir = obj.get("type") == "dir" or bool(obj.get("is_dir"))
            if is_dir:
                await self._walk(obj_uri, collected)
            else:
                collected.append(obj_uri)
