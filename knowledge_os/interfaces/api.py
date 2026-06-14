from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import json
import os

from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel

from knowledge_os.application.extraction_pipeline import ExtractionInputError, ExtractionPipelineResult
from knowledge_os.application.governance import GovernanceService
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
    from core.storage.artifact_store import ArtifactStore


class CandidatePatchRequest(BaseModel):
    edits: list[CandidateEdit]


class LocalPathExtractRequest(BaseModel):
    """Request body for local file-path extraction."""
    path: str
    source_uri: str | None = None
    instructions: str | None = None
    requested_by: str = "pi-agent"
    template_ids: list[str] | None = None


def register_knowledge_os_api(
    app: FastAPI,
    *,
    repository: NexusRepository,
    get_store: Callable[[], KnowledgeOSStore],
    get_extraction_pipeline: Callable[[], CandidateExtractionPipeline | None] | None = None,
    neo4j_store: Any | None = None,
    artifact_store: ArtifactStore | None = None,
    milvus_store: Any | None = None,
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
            except ExtractionInputError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Extraction failed: {exc}",
                ) from exc
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

    @app.post("/api/admin/candidates/extract/file")
    async def admin_extract_from_file(
        file: UploadFile,
        source_uri: str | None = Form(default=None),
        instructions: str | None = Form(default=None),
        requested_by: str = Form(default="pi-agent"),
        template_ids: str | None = Form(default=None),
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Extract candidates from a locally uploaded file.

        The file is processed through the full pipeline (parse → classify →
        LLM extract) without downloading from Cloudreve.  Use *source_uri* to
        set the provenance label (e.g. ``local://my-report.md``); defaults to
        ``local://<uploaded filename>``.

        *template_ids* is an optional JSON array string, e.g.
        ``'["campus_access_control", "campus_sensor"]'``.
        """
        if get_extraction_pipeline is None:
            raise HTTPException(
                status_code=503,
                detail="File extraction unavailable: extraction pipeline not configured.",
            )
        pipeline = get_extraction_pipeline()
        if pipeline is None:
            raise HTTPException(
                status_code=503,
                detail="File extraction unavailable: missing LLM API key.",
            )

        content = await file.read()
        filename = file.filename or "upload"
        uri = source_uri or f"local://{filename}"

        tids: list[str] | None = None
        if template_ids:
            try:
                tids = json.loads(template_ids)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="template_ids must be a JSON array string")

        try:
            result = pipeline.run(
                uri,
                content=content,
                filename=filename,
                instructions=instructions,
                requested_by=requested_by,
                template_ids=tids,
            )
        except ExtractionInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Extraction failed: {exc}",
            ) from exc

        service = CandidateExtractionService(store)
        return {
            **service.describe_batch(result.batch.id),
            "doc_type": result.doc_type,
            "extraction_mode": "local_file",
            "source_uri": uri,
            "warnings": result.warnings,
        }

    @app.post("/api/admin/candidates/extract/path")
    def admin_extract_from_path(
        request: LocalPathExtractRequest,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Extract candidates from a local file path.

        The file is read from the server's local filesystem.  Use
        *source_uri* to override the provenance label; defaults to
        ``local://<filename>``.  Walks the full pipeline: parse →
        classify → LLM extract → persist semantic archive → candidate batch.
        """
        if get_extraction_pipeline is None:
            raise HTTPException(
                status_code=503,
                detail="File extraction unavailable: extraction pipeline not configured.",
            )
        pipeline = get_extraction_pipeline()
        if pipeline is None:
            raise HTTPException(
                status_code=503,
                detail="File extraction unavailable: missing LLM API key.",
            )

        import os as _os
        abs_path = _os.path.abspath(request.path)
        filename = _os.path.basename(abs_path)
        uri = request.source_uri or f"local://{abs_path}"

        try:
            result = pipeline.run(
                uri,
                instructions=request.instructions,
                requested_by=request.requested_by,
                template_ids=request.template_ids,
            )
        except ExtractionInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Extraction failed: {exc}",
            ) from exc

        service = CandidateExtractionService(store)
        return {
            **service.describe_batch(result.batch.id),
            "doc_type": result.doc_type,
            "extraction_mode": "local_path",
            "source_uri": uri,
            "warnings": result.warnings,
        }

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

    @app.delete("/api/admin/documents/{uri:path}/graph")
    def admin_delete_graph_nodes(
        uri: str,
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Hard-delete all Neo4j nodes/edges for a source URI and purge its evidence.

        Irreversible: removes the file node, its relationships, any orphaned
        entity nodes, then purges the Postgres evidence so both stores stay in
        sync.  Also cleans up Milvus vectors and MinIO artifact if configured.
        """
        import logging as _log
        _del_logger = _log.getLogger(__name__)

        if neo4j_store is None:
            raise HTTPException(
                status_code=503,
                detail="Neo4j is not available; cannot perform hard delete.",
            )

        # Fetch parsed_text_key before wiping Postgres so we can clean MinIO.
        parsed_text_key: str | None = None
        try:
            doc = repository.get_document(uri)
            if doc:
                parsed_text_key = doc.get("parsed_text_key")
        except Exception as exc:
            _del_logger.warning("Could not fetch parsed_text_key for %s: %s", uri, exc)

        try:
            neo4j_store.delete_file(uri)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Clean Milvus vectors (non-fatal).
        milvus_deleted = 0
        if milvus_store is not None:
            try:
                milvus_store.delete_chunks_by_uri(uri)
                milvus_deleted = 1  # delete_chunks_by_uri has no return count
            except Exception as exc:
                _del_logger.warning("Milvus delete failed for %s: %s", uri, exc)

        # Delete MinIO artifact (non-fatal).
        artifact_deleted = False
        if parsed_text_key and parsed_text_key.startswith("s3://") and artifact_store is not None:
            try:
                artifact_store.delete(parsed_text_key)
                artifact_deleted = True
            except Exception as exc:
                _del_logger.warning("MinIO artifact delete failed for %s: %s", parsed_text_key, exc)

        evidence = EvidenceService(store, repository=repository).purge(uri, mode="knowledge")
        return {
            "deleted_uri": uri,
            "neo4j": "nodes and edges removed",
            "milvus": "chunks deleted" if milvus_deleted else "skipped (not configured)",
            "artifact": "deleted" if artifact_deleted else "skipped (not s3:// or not configured)",
            "evidence": evidence,
        }

    @app.delete("/api/admin/graph")
    def admin_clear_graph(
        store: KnowledgeOSStore = Depends(get_store),
    ) -> dict[str, Any]:
        """Hard-delete ALL nodes and edges from the Neo4j knowledge graph and purge
        all Postgres graph evidence.

        ⚠️  Irreversible — clears the entire graph, not just one document.
        """
        if neo4j_store is None:
            raise HTTPException(
                status_code=503,
                detail="Neo4j is not available; cannot clear graph.",
            )
        try:
            neo4j_counts = neo4j_store.clear_all()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        evidence = EvidenceService(store, repository=repository).purge_all()
        return {"neo4j": neo4j_counts, "evidence": evidence}

    # ── Documents / chunks read endpoints ─────────────────────────────────────

    @app.get("/api/admin/documents")
    def admin_list_documents(limit: int = 200) -> dict[str, Any]:
        """List semantic_documents stored in Postgres (file metadata + summary)."""
        docs = repository.list_documents(limit=limit)
        return {"documents": docs, "total": len(docs)}

    @app.get("/api/admin/documents/chunks")
    def admin_list_chunks(uri: str) -> dict[str, Any]:
        """List semantic_chunks for a given document URI."""
        chunks = repository.list_chunks(uri)
        return {"uri": uri, "chunks": chunks, "total": len(chunks)}

    @app.get("/api/admin/documents/content")
    def admin_get_document_content(uri: str) -> dict[str, Any]:
        """Return the full parsed text for a document.

        Resolution order:
        1. If ``parsed_text_key`` starts with ``s3://`` and an artifact store is
           configured, stream the text from object storage (MinIO/S3).
        2. If the key starts with ``local://`` or ``file://``, read from the
           local filesystem (server-side path).
        3. If the key starts with ``cloudreve://``, return 410 — this is a
           provenance pointer recorded when MinIO was unavailable; re-extract
           with MinIO configured (or use a local source URI) to make content
           retrievable.
        4. Otherwise return a 422 with a descriptive error.
        """
        doc = repository.get_document(uri)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Document not found: {uri}")

        key: str | None = doc.get("parsed_text_key")
        if not key:
            raise HTTPException(
                status_code=422,
                detail="Document has no parsed_text_key; full text unavailable.",
            )

        # ── MinIO / S3 ────────────────────────────────────────────────────
        if key.startswith("s3://"):
            if artifact_store is None:
                raise HTTPException(
                    status_code=503,
                    detail="Object storage not configured; cannot retrieve s3:// content.",
                )
            try:
                text = artifact_store.read(key)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Object storage read failed: {exc}") from exc
            return {"uri": uri, "parsed_text_key": key, "source": "object_storage", "text": text}

        # ── Local filesystem ──────────────────────────────────────────────
        if key.startswith("local://") or key.startswith("file://"):
            raw_path = key.removeprefix("local://").removeprefix("file://")
            import pathlib
            path = pathlib.Path(raw_path)
            if not path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Local file referenced by parsed_text_key not found: {raw_path}",
                )
            try:
                # Return raw bytes decoded as UTF-8; for binary files this may be imperfect.
                text = path.read_bytes().decode("utf-8", errors="replace")
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Local file read failed: {exc}") from exc
            return {"uri": uri, "parsed_text_key": key, "source": "local_filesystem", "text": text}

        # ── Cloudreve scheme — provenance only, not retrievable ───────────
        # When MinIO is unavailable during extraction, parsed_text_key may fall
        # back to the original cloudreve:// URI as a provenance pointer.  We do
        # not implement a Cloudreve download path here by design; the two systems
        # are kept separate.  Re-extract with MinIO configured to obtain an s3://
        # artifact, or use a local:// source path instead.
        if key.startswith("cloudreve://"):
            raise HTTPException(
                status_code=410,
                detail=(
                    f"Full text not available: parsed_text_key {key!r} is a Cloudreve provenance "
                    "pointer recorded when MinIO was unavailable during extraction.  "
                    "To retrieve content, either configure MinIO and re-extract the document, "
                    "or use a local file path as the source URI."
                ),
            )

        # ── Unknown scheme ────────────────────────────────────────────────
        raise HTTPException(
            status_code=422,
            detail=f"Cannot retrieve content for parsed_text_key scheme: {key!r}",
        )

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
