from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from knowledge_os.application.services import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from knowledge_os.domain.models import CandidateEdit, CandidateExtractionRequest
from knowledge_os.infrastructure.store import KnowledgeOSStore
from nexus.repositories.base import NexusRepository


class CandidatePatchRequest(BaseModel):
    edits: list[CandidateEdit]


def register_knowledge_os_api(
    app: FastAPI,
    *,
    repository: NexusRepository,
    get_store: Callable[[], KnowledgeOSStore],
) -> None:
    """Register Knowledge OS admin routes on an existing FastAPI app."""

    @app.post("/api/admin/candidates/extract")
    def admin_extract_candidates(
        request: CandidateExtractionRequest,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        service = CandidateExtractionService(store)
        batch = service.run(request)
        return service.describe_batch(batch.id)

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
            return GraphCommitService(store, repository=repository).preview(batch_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/admin/candidates/{batch_id}/commit")
    def admin_commit_candidate_batch(
        batch_id: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            return GraphCommitService(store, repository=repository).commit(batch_id).model_dump(mode="json")
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
