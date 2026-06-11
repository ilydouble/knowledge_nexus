from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from knowledge_os.application.services import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from knowledge_os.domain.models import CandidateEdit, CandidateExtractionRequest
from knowledge_os.infrastructure.store import KnowledgeOSStore
from core.repositories.base import NexusRepository

if TYPE_CHECKING:
    from knowledge_os.application.extraction_pipeline import CandidateExtractionPipeline


def register_knowledge_os_tools(
    mcp: Any,
    *,
    store: KnowledgeOSStore,
    get_repository: Callable[[], NexusRepository],
    extraction_pipeline: CandidateExtractionPipeline | None = None,
    neo4j_store: Any | None = None,
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
        """Extract knowledge from a Cloudreve file into a candidate batch (not committed).

        Two modes:
        - Auto (recommended): leave candidate_entities_json/candidate_relations_json empty.
          The pipeline downloads the file, parses it, runs LLM extraction, and stores
          the results as candidates for Pi-Agent review.
        - Manual feed: provide pre-built candidate JSON arrays directly.
        """
        entities = _json_array(candidate_entities_json)
        relations = _json_array(candidate_relations_json)
        template_ids = [str(item) for item in _json_array(template_ids_json)]

        # ── Auto-extract mode ──────────────────────────────────────────────────
        if not entities and not relations:
            if extraction_pipeline is None:
                return json.dumps({
                    "error": (
                        "Auto-extraction unavailable: CandidateExtractionPipeline not initialised. "
                        "Ensure a Cloudreve access token and LLM API key are configured, "
                        "or supply candidate_entities_json/candidate_relations_json manually."
                    )
                }, ensure_ascii=False)
            try:
                result = extraction_pipeline.run(
                    uri,
                    instructions=instructions,
                    requested_by=requested_by,
                    parent_batch_id=parent_batch_id,
                    template_ids=template_ids or None,
                )
                service = CandidateExtractionService(store)
                return json.dumps(
                    {
                        **service.describe_batch(result.batch.id),
                        "doc_type": result.doc_type,
                        "extraction_mode": "auto",
                        "warnings": result.warnings,
                        "next_actions": ["update_candidate_items", "preview_graph_changes", "commit_candidate_batch"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            except Exception as exc:
                return json.dumps({"error": str(exc)}, ensure_ascii=False)

        # ── Manual-feed mode ───────────────────────────────────────────────────
        service = CandidateExtractionService(store)
        batch = service.run(
            CandidateExtractionRequest(
                uri=uri,
                requested_by=requested_by,
                instructions=instructions,
                parent_batch_id=parent_batch_id,
                candidate_entities=entities,
                candidate_relations=relations,
                template_ids=template_ids,
            )
        )
        return json.dumps(
            {
                **service.describe_batch(batch.id),
                "extraction_mode": "manual",
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
            result = GraphCommitService(
                store, repository=get_repository(), neo4j_store=neo4j_store
            ).preview(batch_id).model_dump(mode="json")
        except KeyError as exc:
            result = {"error": str(exc)}
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def commit_candidate_batch(batch_id: str) -> str:
        """Commit accepted candidate items into Neo4j and the knowledge store."""
        try:
            result = GraphCommitService(
                store, repository=get_repository(), neo4j_store=neo4j_store
            ).commit(batch_id).model_dump(mode="json")
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
        """Query the committed knowledge graph to answer a natural-language question.

        Searches Neo4j for entities matching keywords in *question*, retrieves
        their 1-hop neighbourhood and evidence records, and returns structured
        context for Pi-Agent to synthesise a cited answer.

        Args:
            question: The question to answer (natural language).
            include_candidates: If True, also include uncommitted candidate
                batches in the context (useful for 'what was just extracted?').
        """
        from knowledge_os.application.graph_qa import GraphQAService
        result = GraphQAService(
            store=store,
            neo4j_store=neo4j_store,
        ).ask(question, include_candidates=include_candidates)
        return json.dumps(result, ensure_ascii=False, indent=2)

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

    # ── Phase 5: governance tools ──────────────────────────────────────────────

    @mcp.tool()
    def get_knowledge_dashboard() -> str:
        """Return a health dashboard: batch counts, graph item status, stale evidence alerts.

        Use this to get an overview of the knowledge base state before deciding
        what to extract, review, or purge.
        """
        from knowledge_os.application.governance import GovernanceService
        result = GovernanceService(store).dashboard()
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def list_candidate_batches(
        status: str = "",
        source_uri: str = "",
        limit: int = 20,
    ) -> str:
        """List candidate batches with optional filters.

        Args:
            status: Filter by batch status (pending, reviewing, committed). Empty = all.
            source_uri: Filter by exact source URI. Empty = all.
            limit: Maximum batches to return (default 20).
        """
        from knowledge_os.application.governance import GovernanceService
        result = GovernanceService(store).list_batches(
            status=status or None,
            source_uri=source_uri or None,
            limit=limit,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def bulk_review_batch(batch_id: str, action: str) -> str:
        """Bulk-accept or bulk-reject all pending items in a candidate batch.

        Args:
            batch_id: The candidate batch ID.
            action: Either "accept" or "reject".

        Use this when you have reviewed the batch summary and want to approve
        or discard all pending candidates at once, then call commit_candidate_batch.
        """
        from knowledge_os.application.governance import GovernanceService
        try:
            svc = GovernanceService(store)
            if action == "accept":
                result = svc.bulk_accept(batch_id)
            elif action == "reject":
                result = svc.bulk_reject(batch_id)
            else:
                result = {"error": f"Unknown action '{action}'. Use 'accept' or 'reject'."}
        except (KeyError, ValueError) as exc:
            result = {"error": str(exc)}
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
        "get_knowledge_dashboard": get_knowledge_dashboard,
        "list_candidate_batches": list_candidate_batches,
        "bulk_review_batch": bulk_review_batch,
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
