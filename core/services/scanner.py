"""CloudreveScanner – discover all files in Cloudreve and queue them for ingestion.

Design rationale
----------------
The SSE-based worker only sees events that occur *while* it is connected.
Files that existed before the worker started, or files uploaded during a
reconnection gap, are silently missed.

The ``CloudreveScanner`` closes that gap by walking the Cloudreve directory
tree on demand (or on a timer).  It does two things each scan:

1. **Forward pass**: queue any new file (in Cloudreve but not yet known).
2. **Reverse pass**: clean up stale data (in knowledge store but no longer in
   Cloudreve).  Callers supply a ``delete_fn`` callback so the scanner stays
   decoupled from the pipeline and storage backends.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from core.cloudreve.client import CloudreveClient, CloudreveError
from core.models import IngestionJob
from core.repositories.base import NexusRepository

logger = logging.getLogger("core.scanner")


@dataclass
class ScanResult:
    """State snapshot of the most recent scan run."""

    status: str = "idle"  # idle | scanning | done | error
    started_at: datetime | None = None
    finished_at: datetime | None = None
    files_found: int = 0
    files_queued: int = 0
    files_deleted: int = 0   # stale URIs removed from the knowledge store
    error: str | None = None
    discovered_uris: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "files_found": self.files_found,
            "files_queued": self.files_queued,
            "files_deleted": self.files_deleted,
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
        delete_fn: Callable[[str], None] | None = None,
    ) -> ScanResult:
        """Scan *root_uri* recursively, queue new files, and clean up stale data.

        Args:
            root_uri:    Cloudreve directory to walk (default: entire drive).
            requested_by: Label written into queued ingestion jobs.
            delete_fn:  Optional callback ``(uri: str) -> None`` that removes
                        all knowledge data for a URI.  When provided the scanner
                        also performs a **reverse pass**: any URI present in the
                        knowledge store but absent from Cloudreve is cleaned up.
                        Pass ``pipeline.delete_file`` here.

        Returns immediately (with the in-progress result) if a scan is already running.
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
            discovered_set = set(discovered)

            # Determine which URIs are already known to the system.
            # Exclude failed jobs so they get re-queued on the next scan.
            # Include skipped jobs so permanently-skipped files are never re-queued.
            known_uris: set[str] = set(
                job.uri for job in self.repository.list_jobs()
                if job.status in ("pending", "running", "succeeded", "skipped")
            )

            # ── Forward pass: queue newly-discovered files ─────────────────────
            queued = 0
            for uri in discovered:
                if uri not in known_uris:
                    self.repository.add_job(IngestionJob(uri=uri, requested_by=requested_by, status="pending", stage="queued"))
                    queued += 1
            result.files_queued = queued

            # ── Reverse pass: clean up stale knowledge data ────────────────────
            # Only runs when a delete_fn is supplied; skips URIs that are not
            # cloudreve:// paths (e.g. entity:// nodes).
            deleted = 0
            if delete_fn is not None:
                processed_uris = {
                    job.uri for job in self.repository.list_jobs()
                    if job.status == "succeeded"
                    and job.uri
                    and job.uri.startswith("cloudreve://")
                }
                stale_uris = processed_uris - discovered_set

                if stale_uris:
                    if len(stale_uris) == len(processed_uris) and len(discovered) == 0:
                        # All known files appear stale AND Cloudreve returned nothing.
                        # This could mean auth failure or a genuine full wipe.
                        # Proceed but log prominently so the operator can verify.
                        logger.warning(
                            "Cloudreve returned 0 files but knowledge store has %d document(s). "
                            "Proceeding with full cleanup — verify Cloudreve is reachable and "
                            "files are intentionally deleted.",
                            len(processed_uris),
                        )

                    for uri in stale_uris:
                        logger.info("Stale URI detected (no longer in Cloudreve): %s", uri)
                        try:
                            await asyncio.to_thread(delete_fn, uri)
                            deleted += 1
                        except Exception as exc:
                            logger.warning("Failed to delete stale URI %s: %s", uri, exc)
            result.files_deleted = deleted

            result.status = "done"
            result.finished_at = datetime.now(UTC)
            logger.info(
                "Scan complete: %d found, %d queued, %d stale deleted",
                result.files_found,
                result.files_queued,
                result.files_deleted,
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
        """Recursively list *uri* and append file URIs to *collected*.

        Cloudreve Pro v4 response shape (unwrapped ``data`` field)::

            {
                "files": [
                    {"type": 0, "id": "...", "name": "...", "path": "cloudreve://my/file.pdf", ...},
                    {"type": 1, "id": "...", "name": "folder",  "path": "cloudreve://my/folder",  ...},
                ],
                "parent": {...}, "pagination": {...}, ...
            }

        ``type == 0`` → file, ``type == 1`` → directory.
        The ``path`` field is the full Cloudreve URI.
        """
        try:
            items = await self.client.list_files(uri)
        except CloudreveError as exc:
            logger.warning("Cannot list %s: %s", uri, exc)
            return

        if not items:
            return

        # Cloudreve Pro v4 → dict with "files" key.
        # Fallback shapes: "objects" / "items" key, or bare list.
        if isinstance(items, dict):
            objects = (
                items.get("files")
                or items.get("objects")
                or items.get("items")
                or []
            )
        elif isinstance(items, list):
            objects = items
        else:
            return

        for obj in objects:
            # "path" is the full cloudreve:// URI in Pro v4.
            # Fall back to legacy "uri" field.
            obj_uri: str = obj.get("path") or obj.get("uri") or ""
            if not obj_uri:
                continue

            # Pro v4: type 0 = file, type 1 = directory.
            # Legacy string types: "dir" / "file".
            raw_type = obj.get("type")
            is_dir = raw_type == 1 or raw_type == "dir" or bool(obj.get("is_dir"))

            if is_dir:
                await self._walk(obj_uri, collected)
            else:
                collected.append(obj_uri)
