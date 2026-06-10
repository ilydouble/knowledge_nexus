from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from knowledge_os.application.governance import GovernanceService
from knowledge_os.application.services import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from knowledge_os.domain.models import CandidateEdit, CandidateExtractionRequest
from knowledge_os.infrastructure.store import KnowledgeOSStore
from nexus.repositories.base import NexusRepository

if TYPE_CHECKING:
    from knowledge_os.application.extraction_pipeline import CandidateExtractionPipeline


class CandidatePatchRequest(BaseModel):
    edits: list[CandidateEdit]


def register_knowledge_os_api(
    app: FastAPI,
    *,
    repository: NexusRepository,
    get_store: Callable[[], KnowledgeOSStore],
    get_extraction_pipeline: Callable[[], CandidateExtractionPipeline | None] | None = None,
    neo4j_store: Any | None = None,
) -> None:
    """Register Knowledge OS admin routes on an existing FastAPI app."""

    @app.post("/api/admin/candidates/extract")
    def admin_extract_candidates(
        request: CandidateExtractionRequest,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Extract candidates. Auto-mode when no entities/relations are provided."""
        has_candidates = bool(request.candidate_entities or request.candidate_relations)

        # Auto-extract mode: trigger CandidateExtractionPipeline
        if not has_candidates and get_extraction_pipeline is not None:
            pipeline = get_extraction_pipeline()
            if pipeline is None:
                raise HTTPException(
                    status_code=503,
                    detail="Auto-extraction unavailable: missing Cloudreve token or LLM API key.",
                )
            try:
                result = pipeline.run(
                    request.uri,
                    instructions=request.instructions,
                    requested_by=request.requested_by,
                    parent_batch_id=request.parent_batch_id,
                    template_ids=request.template_ids or None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            service = CandidateExtractionService(store)
            return {
                **service.describe_batch(result.batch.id),
                "doc_type": result.doc_type,
                "extraction_mode": "auto",
                "warnings": result.warnings,
            }

        # Manual-feed mode
        service = CandidateExtractionService(store)
        batch = service.run(request)
        return {**service.describe_batch(batch.id), "extraction_mode": "manual"}

    @app.get("/api/admin/candidates/{batch_id}")
    def admin_get_candidate_batch(
        batch_id: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            return CandidateExtractionService(store).describe_batch(batch_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/admin/candidates/{batch_id}")
    def admin_patch_candidate_batch(
        batch_id: str,
        request: CandidatePatchRequest,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            updated = CandidateReviewService(store).apply_edits(batch_id, request.edits)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"batch_id": batch_id, "updated": [item.model_dump(mode="json") for item in updated]}

    @app.post("/api/admin/candidates/{batch_id}/preview")
    def admin_preview_candidate_batch(
        batch_id: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            return GraphCommitService(
                store, repository=repository, neo4j_store=neo4j_store
            ).preview(batch_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/admin/candidates/{batch_id}/commit")
    def admin_commit_candidate_batch(
        batch_id: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            return GraphCommitService(
                store, repository=repository, neo4j_store=neo4j_store
            ).commit(batch_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/admin/graph/evidence")
    def admin_graph_evidence(
        graph_item_id: str | None = None,
        source_uri: str | None = None,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        if graph_item_id:
            return EvidenceService(store, repository=repository).explain(graph_item_id)
        evidence = store.list_graph_evidence(source_uri=source_uri)
        return {"evidence": [item.model_dump(mode="json") for item in evidence]}

    @app.get("/api/admin/graph/stale")
    def admin_stale_evidence(
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """List all stale/purged evidence records grouped by source URI."""
        return GovernanceService(store).stale_report()

    @app.post("/api/admin/documents/{uri:path}/mark-source-deleted")
    def admin_mark_source_deleted(
        uri: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        return EvidenceService(store, repository=repository).mark_source_deleted(uri)

    @app.post("/api/admin/documents/{uri:path}/purge")
    def admin_purge_knowledge(
        uri: str,
        payload: dict[str, str] | None = None,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        mode = (payload or {}).get("mode") or "knowledge"
        return EvidenceService(store, repository=repository).purge(uri, mode=mode)

    # ── Phase 5: governance endpoints ─────────────────────────────────────────

    @app.get("/api/admin/dashboard")
    def admin_dashboard(
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Return aggregate stats: batch counts, item status breakdown, stale evidence."""
        return GovernanceService(store).dashboard()

    @app.get("/api/admin/candidates")
    def admin_list_candidates(
        status: str | None = None,
        source_uri: str | None = None,
        limit: int = 50,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """List candidate batches with optional status/source_uri filters."""
        return GovernanceService(store).list_batches(status=status, source_uri=source_uri, limit=limit)

    @app.post("/api/admin/candidates/{batch_id}/accept-all")
    def admin_accept_all(
        batch_id: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Bulk-accept all pending items in a candidate batch."""
        try:
            return GovernanceService(store).bulk_accept(batch_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/admin/candidates/{batch_id}/reject-all")
    def admin_reject_all(
        batch_id: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Bulk-reject all pending items in a candidate batch."""
        try:
            return GovernanceService(store).bulk_reject(batch_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
