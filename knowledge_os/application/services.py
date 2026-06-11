from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from knowledge_os.domain.models import (
    CandidateBatch,
    CandidateEdit,
    CandidateExtractionRequest,
    CandidateGraphItem,
    CandidateOntology,
    CommitResult,
    GraphChangePreview,
    GraphEvidence,
)
from knowledge_os.infrastructure.store import KnowledgeOSStore
from core.models import GraphEdge, GraphNode, KnowledgeLayer, KnowledgeLink
from core.repositories.base import NexusRepository

if TYPE_CHECKING:
    from core.graph.neo4j_store import Neo4jGraphStore

logger = logging.getLogger("knowledge_os.services")


class CandidateExtractionService:
    def __init__(self, store: KnowledgeOSStore) -> None:
        self.store = store

    def run(self, request: CandidateExtractionRequest) -> CandidateBatch:
        batch = self.store.add_batch(
            CandidateBatch(
                source_uri=request.uri,
                requested_by=request.requested_by,
                template_ids=request.template_ids,
                instructions=request.instructions,
                parent_batch_id=request.parent_batch_id,
            )
        )
        if request.candidate_ontology:
            self.store.add_candidate_ontology(
                CandidateOntology(
                    batch_id=batch.id,
                    name=str(request.candidate_ontology.get("name") or "candidate_ontology"),
                    schema=request.candidate_ontology,
                    confidence=float(request.candidate_ontology.get("confidence", 0.8)),
                )
            )
        for entity in request.candidate_entities:
            payload = self._normalize_entity(entity)
            self.store.add_candidate_graph_item(
                CandidateGraphItem(
                    batch_id=batch.id,
                    kind="node",
                    payload=payload,
                    source_span=self._source_span(entity),
                    confidence=float(entity.get("confidence", 0.8)),
                )
            )
        for relation in request.candidate_relations:
            payload = self._normalize_relation(relation)
            self.store.add_candidate_graph_item(
                CandidateGraphItem(
                    batch_id=batch.id,
                    kind="edge",
                    payload=payload,
                    source_span=self._source_span(relation),
                    confidence=float(relation.get("confidence", 0.8)),
                )
            )
        return batch

    def describe_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self._require_batch(batch_id)
        return {
            "batch": batch.model_dump(mode="json"),
            "ontologies": [
                item.model_dump(mode="json", by_alias=True)
                for item in self.store.list_candidate_ontologies(batch_id)
            ],
            "graph_items": [item.model_dump(mode="json") for item in self.store.list_candidate_graph_items(batch_id)],
        }

    def _require_batch(self, batch_id: str) -> CandidateBatch:
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise KeyError(f"candidate batch not found: {batch_id}")
        return batch

    @staticmethod
    def _normalize_entity(entity: dict[str, Any]) -> dict[str, Any]:
        label = entity.get("label") or entity.get("name") or entity.get("id") or "Unknown"
        entity_id = entity.get("id") or str(label).strip().lower().replace(" ", "_")
        return {
            **entity,
            "id": str(entity_id),
            "label": str(label),
            "type": entity.get("type") or "Concept",
        }

    @staticmethod
    def _normalize_relation(relation: dict[str, Any]) -> dict[str, Any]:
        return {
            **relation,
            "source": str(relation.get("source") or relation.get("from") or ""),
            "target": str(relation.get("target") or relation.get("to") or ""),
            "relation": str(relation.get("relation") or relation.get("type") or "RELATES_TO"),
        }

    @staticmethod
    def _source_span(payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("source_span")
        return raw if isinstance(raw, dict) else {}


class CandidateReviewService:
    def __init__(self, store: KnowledgeOSStore) -> None:
        self.store = store

    def apply_edits(self, batch_id: str, edits: list[CandidateEdit]) -> list[CandidateGraphItem]:
        batch = self._require_batch(batch_id)
        if batch.status == "committed":
            raise ValueError("committed candidate batches cannot be edited")
        updated: list[CandidateGraphItem] = []
        for edit in edits:
            item = self.store.get_candidate_graph_item(edit.item_id)
            if item is None or item.batch_id != batch_id:
                raise KeyError(f"candidate item not found in batch: {edit.item_id}")
            next_item = item.model_copy()
            if edit.status is not None:
                next_item.status = edit.status
            if edit.payload is not None:
                next_item.payload = {**next_item.payload, **edit.payload}
            if edit.review_note is not None:
                next_item.review_note = edit.review_note
            updated.append(self.store.update_candidate_graph_item(next_item))
        return updated

    def _require_batch(self, batch_id: str) -> CandidateBatch:
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise KeyError(f"candidate batch not found: {batch_id}")
        return batch


class GraphCommitService:
    def __init__(
        self,
        store: KnowledgeOSStore,
        repository: NexusRepository | None = None,
        neo4j_store: Neo4jGraphStore | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.neo4j_store = neo4j_store

    def preview(self, batch_id: str) -> GraphChangePreview:
        batch = self._require_batch(batch_id)
        items = self.store.list_candidate_graph_items(batch_id)
        changes = [self._change_for(batch, item) for item in items if item.status == "accepted"]
        return GraphChangePreview(
            batch_id=batch.id,
            source_uri=batch.source_uri,
            summary={
                "candidate_items": len(items),
                "accepted_items": sum(1 for item in items if item.status == "accepted"),
                "rejected_items": sum(1 for item in items if item.status == "rejected"),
                "committed_items": sum(1 for item in items if item.status == "committed"),
            },
            changes=changes,
            warnings=[],
        )

    def commit(self, batch_id: str) -> CommitResult:
        batch = self._require_batch(batch_id)
        items = self.store.list_candidate_graph_items(batch_id)
        committed = 0
        evidence_created = 0
        warnings: list[str] = []

        accepted_nodes = [i for i in items if i.kind == "node" and i.status == "accepted"]
        accepted_edges = [i for i in items if i.kind == "edge" and i.status == "accepted"]

        # ── Write to Neo4j ───────────────────────────────────────────────────
        if self.neo4j_store is not None:
            # 1. Upsert entity nodes first
            for item in accepted_nodes:
                try:
                    self.neo4j_store.upsert_file_node(self._item_to_graph_node(item))
                except Exception as exc:
                    warnings.append(f"Neo4j node write failed ({item.payload.get('id')}): {exc}")
                    logger.warning("Neo4j node write failed: %s", exc)

            # 2. Upsert edges — ensure stub nodes exist for referenced entities
            for item in accepted_edges:
                payload = item.payload
                source_id = str(payload.get("source") or "")
                target_id = str(payload.get("target") or "")
                if not source_id or not target_id:
                    warnings.append(f"Edge item {item.id} missing source/target — skipped.")
                    continue
                try:
                    source_uri = f"entity://{source_id}"
                    target_uri = f"entity://{target_id}"
                    # Ensure stub nodes exist (MERGE is idempotent)
                    stub_layer = KnowledgeLayer.L2
                    self.neo4j_store.upsert_file_node(
                        GraphNode(id=source_id, uri=source_uri, label=source_id, layer=stub_layer, accessible=True)
                    )
                    self.neo4j_store.upsert_file_node(
                        GraphNode(id=target_id, uri=target_uri, label=target_id, layer=stub_layer, accessible=True)
                    )
                    edge = self._item_to_graph_edge(item, batch)
                    self.neo4j_store.upsert_edge(edge, source_uri, target_uri)
                except Exception as exc:
                    warnings.append(f"Neo4j edge write failed ({source_id}→{target_id}): {exc}")
                    logger.warning("Neo4j edge write failed: %s", exc)
        else:
            warnings.append("Neo4j not configured; graph data not written.")

        # ── Write evidence + mark status ─────────────────────────────────────
        for item in items:
            if item.status != "accepted":
                continue
            graph_item_id = self._graph_item_id(item)
            if self.store.list_graph_evidence(graph_item_id=graph_item_id):
                # Already has evidence — just mark committed
                self.store.update_candidate_graph_item(item.model_copy(update={"status": "committed"}))
                continue
            evidence = self.store.add_graph_evidence(
                GraphEvidence(
                    graph_item_id=graph_item_id,
                    source_uri=batch.source_uri,
                    batch_id=batch.id,
                    template_id=batch.template_ids[0] if batch.template_ids else None,
                    evidence_text=item.payload.get("evidence"),
                    confidence=item.confidence,
                )
            )
            evidence_created += 1 if evidence.batch_id == batch.id else 0
            committed += 1
            self._write_repository_link(batch, item)
            self.store.update_candidate_graph_item(item.model_copy(update={"status": "committed"}))

        if batch.status != "committed":
            self.store.update_batch(
                batch.model_copy(update={"status": "committed", "committed_at": datetime.now(UTC)})
            )
        return CommitResult(
            batch_id=batch.id,
            status="committed",
            committed_items=committed,
            skipped_items=len(items) - committed,
            evidence_created=evidence_created,
            warnings=warnings,
        )

    def _require_batch(self, batch_id: str) -> CandidateBatch:
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise KeyError(f"candidate batch not found: {batch_id}")
        return batch

    def _change_for(self, batch: CandidateBatch, item: CandidateGraphItem) -> dict[str, Any]:
        payload = item.payload
        graph_item_id = self._graph_item_id(item)
        existing_evidence = self.store.list_graph_evidence(graph_item_id=graph_item_id)
        if item.kind == "edge":
            return {
                "item_id": item.id,
                "action": "append_evidence" if existing_evidence else "create_edge",
                "source": payload.get("source"),
                "target": payload.get("target"),
                "relation": payload.get("relation"),
                "graph_item_id": graph_item_id,
                "source_uri": batch.source_uri,
                "confidence": item.confidence,
            }
        return {
            "item_id": item.id,
            "action": "append_evidence" if existing_evidence else "create_node",
            "node_id": payload.get("id"),
            "label": payload.get("label"),
            "node_type": payload.get("type"),
            "graph_item_id": graph_item_id,
            "source_uri": batch.source_uri,
            "confidence": item.confidence,
        }

    def _write_repository_link(self, batch: CandidateBatch, item: CandidateGraphItem) -> None:
        if self.repository is None or item.kind != "edge":
            return
        payload = item.payload
        source = payload.get("source")
        target = payload.get("target")
        if not source or not target:
            return
        self.repository.add_link(
            KnowledgeLink(
                id=self._graph_item_id(item),
                source_uri=f"entity://{source}",
                target_uri=f"entity://{target}",
                relation=str(payload.get("relation") or "RELATES_TO"),
                layer=KnowledgeLayer.L2,
                owner_scope=batch.requested_by,
                source_file_uri=batch.source_uri,
                visibility="team",
                created_by=batch.requested_by,
                note=payload.get("evidence"),
            )
        )

    @staticmethod
    def _graph_item_id(item: CandidateGraphItem) -> str:
        payload = item.payload
        if item.kind == "edge":
            return f"edge:{payload.get('source')}:{payload.get('relation')}:{payload.get('target')}"
        return f"node:{payload.get('id')}"

    @staticmethod
    def _item_to_graph_node(item: CandidateGraphItem) -> GraphNode:
        payload = item.payload
        entity_id = str(payload.get("id") or payload.get("label") or item.id)
        return GraphNode(
            id=entity_id,
            uri=f"entity://{entity_id}",
            label=str(payload.get("label") or entity_id),
            summary=payload.get("description") or payload.get("summary"),
            layer=KnowledgeLayer.L2,
            accessible=True,
            properties={"type": payload.get("type") or "Concept", "confidence": item.confidence},
        )

    @staticmethod
    def _item_to_graph_edge(item: CandidateGraphItem, batch: CandidateBatch) -> GraphEdge:
        payload = item.payload
        source_id = str(payload.get("source") or "")
        target_id = str(payload.get("target") or "")
        relation = str(payload.get("relation") or "RELATES_TO")
        return GraphEdge(
            id=f"edge:{source_id}:{relation}:{target_id}",
            source=source_id,
            target=target_id,
            relation=relation,
            layer=KnowledgeLayer.L2,
            owner_scope=batch.requested_by,
            source_file_uri=batch.source_uri,
            visibility="team",
            properties={"evidence": payload.get("evidence") or "", "confidence": item.confidence},
        )


class EvidenceService:
    def __init__(self, store: KnowledgeOSStore, repository: NexusRepository | None = None) -> None:
        self.store = store
        self.repository = repository

    def explain(self, graph_item_id: str) -> dict[str, Any]:
        evidence = self.store.list_graph_evidence(graph_item_id=graph_item_id)
        return {
            "graph_item_id": graph_item_id,
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }

    def mark_source_deleted(self, uri: str) -> dict[str, Any]:
        self.store.mark_document_status(uri, "source_deleted")
        marked = 0
        for item in self.store.list_graph_evidence(source_uri=uri):
            if item.status != "stale":
                self.store.update_graph_evidence(item.model_copy(update={"status": "stale"}))
                marked += 1
        return {"uri": uri, "status": "source_deleted", "evidence_marked_stale": marked}

    def purge(self, uri: str, mode: str = "knowledge") -> dict[str, Any]:
        self.store.mark_document_status(uri, "purged")
        marked = 0
        for item in self.store.list_graph_evidence(source_uri=uri):
            if item.status != "purged":
                self.store.update_graph_evidence(item.model_copy(update={"status": "purged"}))
                marked += 1
        if self.repository is not None:
            self.repository.delete_document(uri)
        return {"uri": uri, "status": "purged", "mode": mode, "evidence_marked_purged": marked}
