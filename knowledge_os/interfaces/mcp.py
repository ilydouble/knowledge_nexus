from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from knowledge_os.application.services import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from knowledge_os.domain.models import CandidateEdit, CandidateExtractionRequest
from knowledge_os.infrastructure.store import KnowledgeOSStore
from nexus.repositories.base import NexusRepository


def register_knowledge_os_tools(
    mcp: Any,
    *,
    store: KnowledgeOSStore,
    get_repository: Callable[[], NexusRepository],
) -> dict[str, Callable[..., str]]:
    """Register Pi-Agent-facing Knowledge OS tools and return them for tests."""

    @mcp.tool()
    def run_candidate_extraction(
        uri: str,
        instructions: str | None = None,
        requested_by: str = "pi-agent",
        candidate_entities_json: str = "[]",
        candidate_relations_json: str = "[]",
        template_ids_json: str = "[]",
        parent_batch_id: str | None = None,
    ) -> str:
        """Create a candidate extraction batch without committing it to the graph."""
        service = CandidateExtractionService(store)
        batch = service.run(
            CandidateExtractionRequest(
                uri=uri,
                requested_by=requested_by,
                instructions=instructions,
                parent_batch_id=parent_batch_id,
                candidate_entities=_json_array(candidate_entities_json),
                candidate_relations=_json_array(candidate_relations_json),
                template_ids=[str(item) for item in _json_array(template_ids_json)],
            )
        )
        return json.dumps(
            {
                **service.describe_batch(batch.id),
                "next_actions": ["update_candidate_items", "preview_graph_changes", "commit_candidate_batch"],
            },
            ensure_ascii=False,
            indent=2,
        )

    @mcp.tool()
    def get_candidate_batch(batch_id: str) -> str:
        """Return candidate ontology and graph items for a batch."""
        try:
            result = CandidateExtractionService(store).describe_batch(batch_id)
        except KeyError as exc:
            result = {"error": str(exc)}
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def update_candidate_items(batch_id: str, edits_json: str) -> str:
        """Apply review edits to candidate graph items."""
        try:
            edits = [CandidateEdit(**item) for item in _json_array(edits_json)]
            updated = CandidateReviewService(store).apply_edits(batch_id, edits)
            result = {
                "batch_id": batch_id,
                "updated": [item.model_dump(mode="json") for item in updated],
                "next_actions": ["preview_graph_changes", "commit_candidate_batch"],
            }
        except (KeyError, ValueError) as exc:
            result = {"error": str(exc)}
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def preview_graph_changes(batch_id: str) -> str:
        """Preview graph diff for accepted candidate items."""
        try:
            result = GraphCommitService(store, repository=get_repository()).preview(batch_id).model_dump(mode="json")
        except KeyError as exc:
            result = {"error": str(exc)}
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def commit_candidate_batch(batch_id: str) -> str:
        """Commit accepted candidate items into the controlled knowledge store."""
        try:
            result = GraphCommitService(store, repository=get_repository()).commit(batch_id).model_dump(mode="json")
        except KeyError as exc:
            result = {"error": str(exc)}
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def explain_graph_evidence(node_or_edge_id: str) -> str:
        """Explain evidence records supporting a committed graph node or edge."""
        result = EvidenceService(store, repository=get_repository()).explain(node_or_edge_id)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def ask_knowledge_graph(question: str, include_candidates: bool = False) -> str:
        """Answer by summarizing available committed documents and optional candidates."""
        docs = [_doc_to_dict(doc) for doc in get_repository().list_documents()]
        payload = {"question": question, "documents": docs}
        if include_candidates:
            payload["candidate_batches"] = [
                {
                    "batch": batch.model_dump(mode="json"),
                    "items": [
                        item.model_dump(mode="json")
                        for item in store.list_candidate_graph_items(batch.id)
                    ],
                }
                for batch in store.list_batches()
            ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @mcp.tool()
    def mark_source_deleted(uri: str) -> str:
        """Mark a source document deleted and stale its evidence without hard purge."""
        result = EvidenceService(store, repository=get_repository()).mark_source_deleted(uri)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def purge_knowledge(uri: str, mode: str = "knowledge") -> str:
        """Explicitly purge knowledge evidence for a source URI."""
        result = EvidenceService(store, repository=get_repository()).purge(uri, mode=mode)
        return json.dumps(result, ensure_ascii=False, indent=2)

    return {
        "run_candidate_extraction": run_candidate_extraction,
        "get_candidate_batch": get_candidate_batch,
        "update_candidate_items": update_candidate_items,
        "preview_graph_changes": preview_graph_changes,
        "commit_candidate_batch": commit_candidate_batch,
        "explain_graph_evidence": explain_graph_evidence,
        "ask_knowledge_graph": ask_knowledge_graph,
        "mark_source_deleted": mark_source_deleted,
        "purge_knowledge": purge_knowledge,
    }


def _json_array(payload: str) -> list:
    try:
        value = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON array: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return value


def _doc_to_dict(doc) -> dict:
    return {
        "uri": doc.uri,
        "summary": doc.summary,
        "tags": doc.tags,
        "entities": doc.entities,
        "chunk_count": len(doc.chunks),
    }
