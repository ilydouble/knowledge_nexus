from __future__ import annotations

from typing import Any, Protocol

from core.models import IngestionJob, KnowledgeLink


class NexusRepository(Protocol):
    def add_job(self, job: IngestionJob) -> IngestionJob: ...

    def get_job(self, job_id: str) -> IngestionJob | None: ...

    def update_job(self, job: IngestionJob) -> IngestionJob: ...

    def list_jobs(self) -> list[IngestionJob]: ...

    def add_link(self, link: KnowledgeLink) -> KnowledgeLink: ...

    def list_links(self) -> list[KnowledgeLink]: ...

    def delete_document(self, uri: str) -> None: ...

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]: ...

    def list_chunks(self, document_uri: str) -> list[dict[str, Any]]: ...

    def upsert_document(self, doc: dict[str, Any]) -> None:
        """Insert or update a semantic_documents record.

        *doc* must include at minimum ``uri``, ``summary``, ``tags``,
        ``entities``, and ``requested_by``.  Optional fields:
        ``filename``, ``source_type``, ``mime_type``, ``size_bytes``,
        ``doc_type``, ``chunk_count``, ``content_hash``, ``active_batch_id``.
        """
        ...

    def replace_chunks(self, document_uri: str, chunks: list[dict[str, Any]]) -> None:
        """Delete all existing chunks for *document_uri* and insert *chunks*.

        Each chunk dict should include: ``id``, ``chunk_index``, ``text``,
        and optionally ``summary``, ``tags``, ``entities``,
        ``char_start``, ``char_end``.
        """
        ...
