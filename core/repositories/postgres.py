from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from core.models import KnowledgeLayer, KnowledgeLink


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


def initialize_postgres_schema(database_url: str) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as connection:
        connection.execute(schema)
        connection.commit()


class PostgresRepository:
    def __init__(self, database_url: str, tenant_id: str = "default") -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id

    def add_link(self, link: KnowledgeLink) -> KnowledgeLink:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_links (
                    id, tenant_id, source_uri, target_uri, relation, layer, owner_scope,
                    source_file_uri, visibility, created_by, note, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    source_uri = EXCLUDED.source_uri,
                    target_uri = EXCLUDED.target_uri,
                    relation = EXCLUDED.relation,
                    layer = EXCLUDED.layer,
                    owner_scope = EXCLUDED.owner_scope,
                    source_file_uri = EXCLUDED.source_file_uri,
                    visibility = EXCLUDED.visibility,
                    created_by = EXCLUDED.created_by,
                    note = EXCLUDED.note,
                    created_at = EXCLUDED.created_at
                """,
                (
                    link.id,
                    self.tenant_id,
                    link.source_uri,
                    link.target_uri,
                    link.relation,
                    link.layer.value,
                    link.owner_scope,
                    link.source_file_uri,
                    link.visibility,
                    link.created_by,
                    link.note,
                    link.created_at,
                ),
            )
            connection.commit()
        return link

    def list_links(self) -> list[KnowledgeLink]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_links WHERE tenant_id = %s ORDER BY created_at ASC, id ASC",
                (self.tenant_id,),
            ).fetchall()
        return [self._link_from_row(row) for row in rows]

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return semantic_documents rows ordered by created_at DESC."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT uri, summary, tags, entities, status, requested_by,
                       created_at, last_seen_at, content_hash, active_batch_id,
                       filename, source_type, mime_type, size_bytes, doc_type, chunk_count,
                       parsed_text_key
                FROM semantic_documents
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (self.tenant_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_document(self, uri: str) -> dict[str, Any] | None:
        """Return a single semantic_documents row, or None if not found."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT uri, summary, tags, entities, status, requested_by,
                       created_at, last_seen_at, content_hash, active_batch_id,
                       filename, source_type, mime_type, size_bytes, doc_type, chunk_count,
                       parsed_text_key
                FROM semantic_documents
                WHERE tenant_id = %s AND uri = %s
                """,
                (self.tenant_id, uri),
            ).fetchone()
        return dict(row) if row else None

    def list_chunks(self, document_uri: str) -> list[dict[str, Any]]:
        """Return semantic_chunks for a given document URI ordered by chunk_index."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, chunk_index, text, summary, tags, entities, char_start, char_end
                FROM semantic_chunks
                WHERE tenant_id = %s AND document_uri = %s
                ORDER BY chunk_index ASC
                """,
                (self.tenant_id, document_uri),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_document(self, doc: dict[str, Any]) -> None:
        """Insert or update a semantic_documents record."""
        import json as _json
        tags = doc.get("tags", [])
        entities = doc.get("entities", [])
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO semantic_documents (
                    uri, tenant_id, summary, tags, entities, requested_by,
                    status, last_seen_at, content_hash, active_batch_id,
                    filename, source_type, mime_type, size_bytes, doc_type, chunk_count,
                    parsed_text_key
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (uri) DO UPDATE SET
                    summary        = EXCLUDED.summary,
                    tags           = EXCLUDED.tags,
                    entities       = EXCLUDED.entities,
                    status         = EXCLUDED.status,
                    last_seen_at   = now(),
                    content_hash   = EXCLUDED.content_hash,
                    active_batch_id= EXCLUDED.active_batch_id,
                    filename       = EXCLUDED.filename,
                    source_type    = EXCLUDED.source_type,
                    mime_type      = EXCLUDED.mime_type,
                    size_bytes     = EXCLUDED.size_bytes,
                    doc_type       = EXCLUDED.doc_type,
                    chunk_count    = EXCLUDED.chunk_count,
                    parsed_text_key= EXCLUDED.parsed_text_key
                """,
                (
                    doc["uri"],
                    self.tenant_id,
                    doc.get("summary", ""),
                    _json.dumps(tags if isinstance(tags, list) else list(tags)),
                    _json.dumps(entities if isinstance(entities, list) else list(entities)),
                    doc.get("requested_by", "system"),
                    doc.get("status", "active"),
                    doc.get("content_hash"),
                    doc.get("active_batch_id"),
                    doc.get("filename"),
                    doc.get("source_type", "local"),
                    doc.get("mime_type"),
                    doc.get("size_bytes"),
                    doc.get("doc_type"),
                    doc.get("chunk_count", 0),
                    doc.get("parsed_text_key"),
                ),
            )
            connection.commit()

    def replace_chunks(self, document_uri: str, chunks: list[dict[str, Any]]) -> None:
        """Delete all existing chunks for *document_uri* and insert *chunks*."""
        import json as _json
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM semantic_chunks WHERE tenant_id = %s AND document_uri = %s",
                (self.tenant_id, document_uri),
            )
            for chunk in chunks:
                tags = chunk.get("tags", [])
                entities = chunk.get("entities", [])
                connection.execute(
                    """
                    INSERT INTO semantic_chunks (
                        id, tenant_id, document_uri, chunk_index, text,
                        summary, tags, entities, char_start, char_end
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        chunk_index = EXCLUDED.chunk_index,
                        text        = EXCLUDED.text,
                        summary     = EXCLUDED.summary,
                        tags        = EXCLUDED.tags,
                        entities    = EXCLUDED.entities,
                        char_start  = EXCLUDED.char_start,
                        char_end    = EXCLUDED.char_end
                    """,
                    (
                        chunk["id"],
                        self.tenant_id,
                        document_uri,
                        chunk["chunk_index"],
                        chunk.get("text", ""),
                        chunk.get("summary"),
                        _json.dumps(tags if isinstance(tags, list) else list(tags)),
                        _json.dumps(entities if isinstance(entities, list) else list(entities)),
                        chunk.get("char_start"),
                        chunk.get("char_end"),
                    ),
                )
            connection.commit()

    def delete_document(self, uri: str) -> None:
        """Delete a document record and its associated chunks from Postgres."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM semantic_documents WHERE tenant_id = %s AND uri = %s",
                (self.tenant_id, uri),
            )
            connection.commit()

    def delete_by_uri_for_tests(self, uri: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM knowledge_links WHERE tenant_id = %s AND (source_uri = %s OR target_uri = %s)", (self.tenant_id, uri, uri))
            connection.execute("DELETE FROM semantic_documents WHERE tenant_id = %s AND uri = %s", (self.tenant_id, uri))
            connection.commit()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _link_from_row(row: dict[str, Any]) -> KnowledgeLink:
        return KnowledgeLink(
            id=row["id"],
            source_uri=row["source_uri"],
            target_uri=row["target_uri"],
            relation=row["relation"],
            layer=KnowledgeLayer(row["layer"]),
            owner_scope=row["owner_scope"],
            source_file_uri=row["source_file_uri"],
            visibility=row["visibility"],
            created_by=row["created_by"],
            note=row["note"],
            created_at=row["created_at"],
        )

