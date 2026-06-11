from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from core.models import IngestionJob, KnowledgeLayer, KnowledgeLink


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

    def add_job(self, job: IngestionJob) -> IngestionJob:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_jobs (
                    id, tenant_id, uri, requested_by, status, stage, attempts,
                    created_at, started_at, finished_at, error_code, error
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    uri = EXCLUDED.uri,
                    requested_by = EXCLUDED.requested_by,
                    status = EXCLUDED.status,
                    stage = EXCLUDED.stage,
                    attempts = EXCLUDED.attempts,
                    created_at = EXCLUDED.created_at,
                    started_at = EXCLUDED.started_at,
                    finished_at = EXCLUDED.finished_at,
                    error_code = EXCLUDED.error_code,
                    error = EXCLUDED.error
                """,
                (
                    job.id,
                    self.tenant_id,
                    job.uri,
                    job.requested_by,
                    job.status,
                    job.stage,
                    job.attempts,
                    job.created_at,
                    job.started_at,
                    job.finished_at,
                    job.error_code,
                    job.error,
                ),
            )
            connection.commit()
        return job

    def get_job(self, job_id: str) -> IngestionJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE id = %s AND tenant_id = %s",
                (job_id, self.tenant_id),
            ).fetchone()
        return self._job_from_row(row) if row else None

    def update_job(self, job: IngestionJob) -> IngestionJob:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = %s,
                    stage = %s,
                    attempts = %s,
                    started_at = %s,
                    finished_at = %s,
                    error_code = %s,
                    error = %s
                WHERE id = %s AND tenant_id = %s
                """,
                (job.status, job.stage, job.attempts, job.started_at, job.finished_at, job.error_code, job.error, job.id, self.tenant_id),
            )
            connection.commit()
        return job

    def list_jobs(self) -> list[IngestionJob]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE tenant_id = %s ORDER BY created_at DESC, id DESC",
                (self.tenant_id,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

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
            connection.execute("DELETE FROM ingestion_jobs WHERE tenant_id = %s AND uri = %s", (self.tenant_id, uri))
            connection.execute("DELETE FROM semantic_documents WHERE tenant_id = %s AND uri = %s", (self.tenant_id, uri))
            connection.commit()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _job_from_row(row: dict[str, Any]) -> IngestionJob:
        return IngestionJob(
            id=row["id"],
            uri=row["uri"],
            requested_by=row["requested_by"],
            status=row["status"],
            stage=row.get("stage") or "queued",
            attempts=row["attempts"],
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
            error_code=row.get("error_code"),
            error=row["error"],
        )

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


