from __future__ import annotations

import datetime
from typing import Any

from core.models import KnowledgeLink


class InMemoryRepository:
    def __init__(self) -> None:
        self.links: dict[str, KnowledgeLink] = {}
        self._documents: dict[str, dict[str, Any]] = {}
        self._chunks: dict[str, list[dict[str, Any]]] = {}  # uri → chunk list

    def add_link(self, link: KnowledgeLink) -> KnowledgeLink:
        self.links[link.id] = link
        return link

    def list_links(self) -> list[KnowledgeLink]:
        return list(self.links.values())

    def delete_document(self, uri: str) -> None:
        self._documents.pop(uri, None)
        self._chunks.pop(uri, None)

    def get_document(self, uri: str) -> dict[str, Any] | None:
        return self._documents.get(uri)

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        docs = sorted(
            self._documents.values(),
            key=lambda d: d.get("created_at", ""),
            reverse=True,
        )
        return docs[:limit]

    def list_chunks(self, document_uri: str) -> list[dict[str, Any]]:
        return sorted(
            self._chunks.get(document_uri, []),
            key=lambda c: c.get("chunk_index", 0),
        )

    def upsert_document(self, doc: dict[str, Any]) -> None:
        uri = doc["uri"]
        existing = self._documents.get(uri, {})
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        merged = {
            "uri": uri,
            "summary": doc.get("summary", ""),
            "tags": doc.get("tags", []),
            "entities": doc.get("entities", []),
            "requested_by": doc.get("requested_by", "system"),
            "status": doc.get("status", "active"),
            "created_at": existing.get("created_at", now),
            "last_seen_at": now,
            "content_hash": doc.get("content_hash"),
            "active_batch_id": doc.get("active_batch_id"),
            "filename": doc.get("filename"),
            "source_type": doc.get("source_type", "local"),
            "mime_type": doc.get("mime_type"),
            "size_bytes": doc.get("size_bytes"),
            "doc_type": doc.get("doc_type"),
            "chunk_count": doc.get("chunk_count", 0),
            # Pointer to full parsed text (source URI or future s3:// key).
            "parsed_text_key": doc.get("parsed_text_key"),
        }
        self._documents[uri] = merged

    def replace_chunks(self, document_uri: str, chunks: list[dict[str, Any]]) -> None:
        self._chunks[document_uri] = [dict(c) for c in chunks]
