from __future__ import annotations

from datetime import UTC, datetime

from nexus.knowledge_os.domain.models import (
    CandidateBatch,
    CandidateGraphItem,
    CandidateOntology,
    GraphEvidence,
)


class InMemoryKnowledgeOSStore:
    def __init__(self) -> None:
        self.batches: dict[str, CandidateBatch] = {}
        self.ontologies: dict[str, CandidateOntology] = {}
        self.graph_items: dict[str, CandidateGraphItem] = {}
        self.evidence: dict[str, GraphEvidence] = {}
        self.document_status: dict[str, str] = {}
        self.document_deleted_at: dict[str, datetime] = {}

    def add_batch(self, batch: CandidateBatch) -> CandidateBatch:
        self.batches[batch.id] = batch
        self.document_status.setdefault(batch.source_uri, "active")
        return batch

    def get_batch(self, batch_id: str) -> CandidateBatch | None:
        return self.batches.get(batch_id)

    def update_batch(self, batch: CandidateBatch) -> CandidateBatch:
        self.batches[batch.id] = batch
        return batch

    def list_batches(self) -> list[CandidateBatch]:
        return sorted(self.batches.values(), key=lambda batch: batch.created_at, reverse=True)

    def add_candidate_ontology(self, ontology: CandidateOntology) -> CandidateOntology:
        self.ontologies[ontology.id] = ontology
        return ontology

    def list_candidate_ontologies(self, batch_id: str) -> list[CandidateOntology]:
        return [ontology for ontology in self.ontologies.values() if ontology.batch_id == batch_id]

    def add_candidate_graph_item(self, item: CandidateGraphItem) -> CandidateGraphItem:
        self.graph_items[item.id] = item
        return item

    def get_candidate_graph_item(self, item_id: str) -> CandidateGraphItem | None:
        return self.graph_items.get(item_id)

    def update_candidate_graph_item(self, item: CandidateGraphItem) -> CandidateGraphItem:
        self.graph_items[item.id] = item
        return item

    def list_candidate_graph_items(self, batch_id: str) -> list[CandidateGraphItem]:
        return [item for item in self.graph_items.values() if item.batch_id == batch_id]

    def add_graph_evidence(self, evidence: GraphEvidence) -> GraphEvidence:
        existing = [
            item for item in self.evidence.values()
            if item.graph_item_id == evidence.graph_item_id and item.batch_id == evidence.batch_id
        ]
        if existing:
            return existing[0]
        self.evidence[evidence.id] = evidence
        return evidence

    def list_graph_evidence(self, source_uri: str | None = None, graph_item_id: str | None = None) -> list[GraphEvidence]:
        evidence = list(self.evidence.values())
        if source_uri is not None:
            evidence = [item for item in evidence if item.source_uri == source_uri]
        if graph_item_id is not None:
            evidence = [item for item in evidence if item.graph_item_id == graph_item_id]
        return evidence

    def update_graph_evidence(self, evidence: GraphEvidence) -> GraphEvidence:
        self.evidence[evidence.id] = evidence
        return evidence

    def mark_document_status(self, uri: str, status: str) -> None:
        self.document_status[uri] = status
        if status == "source_deleted":
            self.document_deleted_at[uri] = datetime.now(UTC)

    def get_document_status(self, uri: str) -> str | None:
        return self.document_status.get(uri)
