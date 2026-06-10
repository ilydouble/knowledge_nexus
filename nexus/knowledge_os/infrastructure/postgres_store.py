from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from nexus.knowledge_os.domain.models import (
    CandidateBatch,
    CandidateGraphItem,
    CandidateOntology,
    GraphEvidence,
)


class PostgresKnowledgeOSStore:
    def __init__(self, database_url: str, tenant_id: str = "default") -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id

    def add_batch(self, batch: CandidateBatch) -> CandidateBatch:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO extraction_batches (
                    id, tenant_id, source_uri, requested_by, status, template_ids,
                    instructions, parent_batch_id, created_at, committed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    template_ids = EXCLUDED.template_ids,
                    instructions = EXCLUDED.instructions,
                    committed_at = EXCLUDED.committed_at
                """,
                (
                    batch.id,
                    self.tenant_id,
                    batch.source_uri,
                    batch.requested_by,
                    batch.status,
                    Jsonb(batch.template_ids),
                    batch.instructions,
                    batch.parent_batch_id,
                    batch.created_at,
                    batch.committed_at,
                ),
            )
            connection.execute(
                """
                UPDATE semantic_documents
                SET status = 'active', last_seen_at = COALESCE(last_seen_at, now())
                WHERE tenant_id = %s AND uri = %s
                """,
                (self.tenant_id, batch.source_uri),
            )
            connection.commit()
        return batch

    def get_batch(self, batch_id: str) -> CandidateBatch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM extraction_batches WHERE tenant_id = %s AND id = %s",
                (self.tenant_id, batch_id),
            ).fetchone()
        return self._batch_from_row(row) if row else None

    def update_batch(self, batch: CandidateBatch) -> CandidateBatch:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE extraction_batches
                SET status = %s, template_ids = %s, instructions = %s, committed_at = %s
                WHERE tenant_id = %s AND id = %s
                """,
                (
                    batch.status,
                    Jsonb(batch.template_ids),
                    batch.instructions,
                    batch.committed_at,
                    self.tenant_id,
                    batch.id,
                ),
            )
            connection.commit()
        return batch

    def list_batches(self) -> list[CandidateBatch]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM extraction_batches WHERE tenant_id = %s ORDER BY created_at DESC, id DESC",
                (self.tenant_id,),
            ).fetchall()
        return [self._batch_from_row(row) for row in rows]

    def add_candidate_ontology(self, ontology: CandidateOntology) -> CandidateOntology:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO candidate_ontologies (
                    id, tenant_id, batch_id, name, schema, status, confidence, review_note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    schema = EXCLUDED.schema,
                    status = EXCLUDED.status,
                    confidence = EXCLUDED.confidence,
                    review_note = EXCLUDED.review_note
                """,
                (
                    ontology.id,
                    self.tenant_id,
                    ontology.batch_id,
                    ontology.name,
                    Jsonb(ontology.schema_payload),
                    ontology.status,
                    ontology.confidence,
                    ontology.review_note,
                ),
            )
            connection.commit()
        return ontology

    def list_candidate_ontologies(self, batch_id: str) -> list[CandidateOntology]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM candidate_ontologies
                WHERE tenant_id = %s AND batch_id = %s
                ORDER BY id ASC
                """,
                (self.tenant_id, batch_id),
            ).fetchall()
        return [self._ontology_from_row(row) for row in rows]

    def add_candidate_graph_item(self, item: CandidateGraphItem) -> CandidateGraphItem:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO candidate_graph_items (
                    id, tenant_id, batch_id, kind, payload, source_span,
                    confidence, status, review_note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    source_span = EXCLUDED.source_span,
                    confidence = EXCLUDED.confidence,
                    status = EXCLUDED.status,
                    review_note = EXCLUDED.review_note
                """,
                (
                    item.id,
                    self.tenant_id,
                    item.batch_id,
                    item.kind,
                    Jsonb(item.payload),
                    Jsonb(item.source_span),
                    item.confidence,
                    item.status,
                    item.review_note,
                ),
            )
            connection.commit()
        return item

    def get_candidate_graph_item(self, item_id: str) -> CandidateGraphItem | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM candidate_graph_items WHERE tenant_id = %s AND id = %s",
                (self.tenant_id, item_id),
            ).fetchone()
        return self._graph_item_from_row(row) if row else None

    def update_candidate_graph_item(self, item: CandidateGraphItem) -> CandidateGraphItem:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE candidate_graph_items
                SET payload = %s, source_span = %s, confidence = %s, status = %s, review_note = %s
                WHERE tenant_id = %s AND id = %s
                """,
                (
                    Jsonb(item.payload),
                    Jsonb(item.source_span),
                    item.confidence,
                    item.status,
                    item.review_note,
                    self.tenant_id,
                    item.id,
                ),
            )
            connection.commit()
        return item

    def list_candidate_graph_items(self, batch_id: str) -> list[CandidateGraphItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM candidate_graph_items
                WHERE tenant_id = %s AND batch_id = %s
                ORDER BY id ASC
                """,
                (self.tenant_id, batch_id),
            ).fetchall()
        return [self._graph_item_from_row(row) for row in rows]

    def add_graph_evidence(self, evidence: GraphEvidence) -> GraphEvidence:
        existing = self.list_graph_evidence(graph_item_id=evidence.graph_item_id)
        for item in existing:
            if item.batch_id == evidence.batch_id:
                return item
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO graph_evidence (
                    id, tenant_id, graph_item_id, source_uri, batch_id, template_id,
                    evidence_text, confidence, status, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    evidence.id,
                    self.tenant_id,
                    evidence.graph_item_id,
                    evidence.source_uri,
                    evidence.batch_id,
                    evidence.template_id,
                    evidence.evidence_text,
                    evidence.confidence,
                    evidence.status,
                    evidence.created_at,
                ),
            )
            connection.commit()
        return evidence

    def list_graph_evidence(self, source_uri: str | None = None, graph_item_id: str | None = None) -> list[GraphEvidence]:
        clauses = ["tenant_id = %s"]
        params: list[Any] = [self.tenant_id]
        if source_uri is not None:
            clauses.append("source_uri = %s")
            params.append(source_uri)
        if graph_item_id is not None:
            clauses.append("graph_item_id = %s")
            params.append(graph_item_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM graph_evidence WHERE {' AND '.join(clauses)} ORDER BY created_at ASC, id ASC",
                params,
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def update_graph_evidence(self, evidence: GraphEvidence) -> GraphEvidence:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE graph_evidence
                SET evidence_text = %s, confidence = %s, status = %s
                WHERE tenant_id = %s AND id = %s
                """,
                (
                    evidence.evidence_text,
                    evidence.confidence,
                    evidence.status,
                    self.tenant_id,
                    evidence.id,
                ),
            )
            connection.commit()
        return evidence

    def mark_document_status(self, uri: str, status: str) -> None:
        deleted_at = datetime.now(UTC) if status == "source_deleted" else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE semantic_documents
                SET status = %s, deleted_at = COALESCE(%s, deleted_at)
                WHERE tenant_id = %s AND uri = %s
                """,
                (status, deleted_at, self.tenant_id, uri),
            )
            connection.commit()

    def get_document_status(self, uri: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM semantic_documents WHERE tenant_id = %s AND uri = %s",
                (self.tenant_id, uri),
            ).fetchone()
        return row["status"] if row else None

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _batch_from_row(row: dict[str, Any]) -> CandidateBatch:
        return CandidateBatch(
            id=row["id"],
            source_uri=row["source_uri"],
            requested_by=row["requested_by"],
            status=row["status"],
            template_ids=list(row["template_ids"] or []),
            instructions=row["instructions"],
            parent_batch_id=row["parent_batch_id"],
            created_at=row["created_at"],
            committed_at=row["committed_at"],
        )

    @staticmethod
    def _ontology_from_row(row: dict[str, Any]) -> CandidateOntology:
        return CandidateOntology(
            id=row["id"],
            batch_id=row["batch_id"],
            name=row["name"],
            schema=row["schema"] or {},
            status=row["status"],
            confidence=row["confidence"],
            review_note=row["review_note"],
        )

    @staticmethod
    def _graph_item_from_row(row: dict[str, Any]) -> CandidateGraphItem:
        return CandidateGraphItem(
            id=row["id"],
            batch_id=row["batch_id"],
            kind=row["kind"],
            payload=row["payload"] or {},
            source_span=row["source_span"] or {},
            confidence=row["confidence"],
            status=row["status"],
            review_note=row["review_note"],
        )

    @staticmethod
    def _evidence_from_row(row: dict[str, Any]) -> GraphEvidence:
        return GraphEvidence(
            id=row["id"],
            graph_item_id=row["graph_item_id"],
            source_uri=row["source_uri"],
            batch_id=row["batch_id"],
            template_id=row["template_id"],
            evidence_text=row["evidence_text"],
            confidence=row["confidence"],
            status=row["status"],
            created_at=row["created_at"],
        )
