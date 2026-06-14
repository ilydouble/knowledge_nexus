from __future__ import annotations

from typing import Any

import mimetypes
import os

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from pydantic import BaseModel

from core.cloudreve.client import CloudreveClient
from core.cloudreve.oauth import (
    CloudreveOAuthConfigStore,
    CloudreveOAuthError,
    CloudreveOAuthTokenStore,
    build_authorization_url,
    exchange_authorization_code,
    refresh_oauth_tokens,
    resolve_oauth_settings,
)
from core.graph.neo4j_store import Neo4jGraphStore
from knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from knowledge_os.infrastructure.postgres_store import PostgresKnowledgeOSStore
from knowledge_os.infrastructure.store import KnowledgeOSStore
from knowledge_os.interfaces.api import register_knowledge_os_api
from core.models import KnowledgeLayer
from core.repositories.base import NexusRepository
from core.repositories.memory import InMemoryRepository
from core.repositories.postgres import PostgresRepository
from core.services.scanner import CloudreveScanner
from core.services.embedding import BigModelEmbeddingService, DeterministicEmbeddingService
from core.settings import Settings
from core.vector.milvus_store import MilvusVectorStore


class GraphAskRequest(BaseModel):
    question: str
    requested_by: str = "system"


def build_repository(settings: Settings) -> NexusRepository:
    if settings.nexus_storage_backend == "postgres":
        return PostgresRepository(settings.database_url)
    if settings.nexus_storage_backend == "memory":
        return InMemoryRepository()
    raise ValueError(f"Unsupported NEXUS_STORAGE_BACKEND: {settings.nexus_storage_backend}")


def build_knowledge_os_store(settings: Settings, repository: NexusRepository | None = None) -> KnowledgeOSStore:
    if isinstance(repository, PostgresRepository) or (repository is None and settings.nexus_storage_backend == "postgres"):
        return PostgresKnowledgeOSStore(settings.database_url)
    return InMemoryKnowledgeOSStore()


def create_application(repository: NexusRepository | None = None, settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Knowledge OS API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app_settings = settings or Settings.from_env()
    repo = repository or build_repository(app_settings)
    app.state.settings = app_settings
    app.state.repository = repo
    # Scanner is Cloudreve-specific; build with an empty-token client so it
    # starts without crashing when no OAuth token is present.
    _scanner_client = CloudreveClient(token="")
    app.state.scanner = CloudreveScanner(_scanner_client, repo)
    app.state.knowledge_os_store = build_knowledge_os_store(app_settings, repo)

    # Neo4j graph store — used by the /api/graph endpoint.
    # Falls back gracefully if Neo4j is not configured.
    _neo4j_store: Neo4jGraphStore | None = None
    if app_settings.neo4j_uri and app_settings.neo4j_user and app_settings.neo4j_password:
        try:
            _neo4j_store = Neo4jGraphStore(
                uri=app_settings.neo4j_uri,
                user=app_settings.neo4j_user,
                password=app_settings.neo4j_password,
            )
        except Exception:
            pass

    # Embedding service — shared between pipeline and Agent3
    _llm_api_key = app_settings.zhipu_api_key or app_settings.openai_api_key
    if _llm_api_key:
        _embedding_service: BigModelEmbeddingService | DeterministicEmbeddingService = BigModelEmbeddingService(
            api_key=_llm_api_key,
            model=app_settings.embedding_model,
            dimensions=app_settings.embedding_dimensions,
            base_url=app_settings.embedding_base_url,
        )
    else:
        _embedding_service = DeterministicEmbeddingService(dimensions=64)

    # Milvus vector store — used by Agent3 vector_search tool
    _milvus_store: MilvusVectorStore | None = None
    if app_settings.vector_backend.lower() == "milvus" and app_settings.milvus_host:
        try:
            _milvus_store = MilvusVectorStore(
                host=app_settings.milvus_host,
                port=app_settings.milvus_port,
                dimensions=_embedding_service.dimensions,
            )
        except Exception:
            pass

    # Graph Q&A Agent (Agent3) — built lazily; None when stores are unavailable
    _graph_qa_agent = None
    if _neo4j_store is not None and _llm_api_key:
        try:
            from core.agents.graph_qa_agent import create_graph_qa_agent  # lazy
            _graph_qa_agent = create_graph_qa_agent(
                neo4j_store=_neo4j_store,
                milvus_store=_milvus_store,  # type: ignore[arg-type]  # None → tool skips gracefully
                embedding_service=_embedding_service,  # type: ignore[arg-type]
                settings=app_settings,
            )
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger(__name__).warning("Could not initialise graph QA agent: %s", _exc)

    def get_repository() -> NexusRepository:
        return repo

    def get_knowledge_os_store() -> KnowledgeOSStore:
        return app.state.knowledge_os_store

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/auth/cloudreve/bind")
    def bind_cloudreve(payload: dict[str, str]) -> dict[str, str]:
        token = payload.get("token")
        if not token:
            raise HTTPException(status_code=400, detail="token is required")
        return {"status": "bound"}

    @app.get("/api/auth/cloudreve/config")
    def get_cloudreve_oauth_config() -> dict[str, Any]:
        config_store = CloudreveOAuthConfigStore(app_settings.cloudreve_oauth_config_path)
        status = config_store.status()
        resolved = resolve_oauth_settings(app_settings)
        return {
            **status,
            "cloudreve_base_url": status.get("cloudreve_base_url") or resolved.cloudreve_base_url,
            "redirect_uri": status.get("redirect_uri") or resolved.cloudreve_oauth_redirect_uri,
            "scope": status.get("scope") or resolved.cloudreve_oauth_scope,
        }

    @app.post("/api/auth/cloudreve/config")
    def save_cloudreve_oauth_config(payload: dict[str, str]) -> dict[str, Any]:
        config_store = CloudreveOAuthConfigStore(app_settings.cloudreve_oauth_config_path)
        config_store.save(
            {
                "cloudreve_base_url": payload.get("cloudreve_base_url") or app_settings.cloudreve_base_url,
                "client_id": payload.get("client_id"),
                "client_secret": payload.get("client_secret"),
                "redirect_uri": payload.get("redirect_uri") or app_settings.cloudreve_oauth_redirect_uri,
                "scope": payload.get("scope") or "openid profile offline_access Files.Read",
            }
        )
        return config_store.status()

    @app.get("/api/auth/cloudreve/start")
    def start_cloudreve_oauth() -> RedirectResponse:
        oauth_settings = resolve_oauth_settings(app_settings)
        try:
            return RedirectResponse(build_authorization_url(oauth_settings))
        except CloudreveOAuthError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "oauth_config_required",
                    "message": str(exc),
                    "redirect_uri": oauth_settings.cloudreve_oauth_redirect_uri,
                    "required_scope": "openid profile offline_access Files.Read",
                },
            ) from exc

    @app.get("/api/auth/cloudreve/callback")
    def cloudreve_oauth_callback(code: str | None = None) -> dict[str, Any]:
        if not code:
            raise HTTPException(status_code=400, detail="code is required")
        oauth_settings = resolve_oauth_settings(app_settings)
        try:
            tokens = exchange_authorization_code(oauth_settings, code)
        except CloudreveOAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        CloudreveOAuthTokenStore(app_settings.cloudreve_token_store_path).save(tokens)
        return {
            "status": "authorized",
            "has_refresh_token": bool(tokens.get("refresh_token")),
        }

    @app.get("/api/auth/cloudreve/status")
    def cloudreve_oauth_status() -> dict[str, Any]:
        store = CloudreveOAuthTokenStore(app_settings.cloudreve_token_store_path)
        tokens = store.load()
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            return {"authorized": False}
        oauth_settings = resolve_oauth_settings(app_settings)
        try:
            refreshed_tokens = refresh_oauth_tokens(oauth_settings, refresh_token)
        except CloudreveOAuthError:
            return {"authorized": False, "has_refresh_token": True, "error": "refresh_failed"}
        store.save(refreshed_tokens)
        return store.status()

    @app.get("/api/graph")
    def get_graph(uri: str | None = None, limit: int = 500):
        """Return the Neo4j knowledge graph.

        - Without ``uri``: return the full graph (up to *limit* nodes/edges).
        - With ``uri``: return the 1-hop neighborhood of the given document.
        """
        if _neo4j_store is None:
            return {"nodes": [], "edges": [], "hidden_node_count": 0, "error": "Neo4j not configured"}
        all_layers = [KnowledgeLayer.L1, KnowledgeLayer.L2, KnowledgeLayer.L3]
        if uri:
            result = _neo4j_store.neighborhood(uri, layers=all_layers)
        else:
            result = _neo4j_store.full_graph(limit=limit)
        return result

    @app.post("/api/graph/ask")
    def graph_ask(request: GraphAskRequest) -> dict[str, Any]:
        """Answer a natural-language question using the knowledge graph (Agent3).

        Requires Neo4j to be configured and an LLM API key to be set.
        """
        if _graph_qa_agent is None:
            raise HTTPException(
                status_code=503,
                detail="Graph Q&A agent is not available (Neo4j or LLM API key not configured)",
            )
        from core.agents.graph_qa_agent import ask as agent_ask
        answer = agent_ask(request.question, _graph_qa_agent)
        return {"question": request.question, "answer": answer}

    # Artifact store — persists full parsed text (MinIO or local filesystem).
    # Falls back to LocalArtifactStore when MinIO is unreachable so
    # parsed_text_key always resolves to a readable local:// URI.
    from core.storage.artifact_store import build_artifact_store
    _artifact_store = build_artifact_store(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_access_key,
        secret_key=app_settings.minio_secret_key,
        bucket=app_settings.minio_bucket,
        local_dir=app_settings.artifact_local_dir,
    )

    # Build CandidateExtractionPipeline — lazy, returns None if prerequisites missing.
    # Pass repo so the pipeline can persist semantic_documents / semantic_chunks.
    from knowledge_os.application.extraction_pipeline import build_candidate_extraction_pipeline
    _extraction_pipeline = build_candidate_extraction_pipeline(
        app_settings, app.state.knowledge_os_store, repository=repo,
        artifact_store=_artifact_store,
        embedding_service=_embedding_service,
        milvus_store=_milvus_store,
    )

    def get_extraction_pipeline():
        return _extraction_pipeline

    register_knowledge_os_api(
        app,
        repository=repo,
        get_store=get_knowledge_os_store,
        get_extraction_pipeline=get_extraction_pipeline,
        neo4j_store=_neo4j_store,
        artifact_store=_artifact_store,
        milvus_store=_milvus_store,
    )

    # ------------------------------------------------------------------
    # Cloudreve full-scan endpoints
    # ------------------------------------------------------------------

    @app.get("/api/cloudreve/scan/status")
    def cloudreve_scan_status() -> dict[str, Any]:
        """Return the most recent scan result (or idle state if never run)."""
        scanner: CloudreveScanner = app.state.scanner
        result = scanner.last_result()
        return {**result.to_dict(), "is_scanning": scanner.is_scanning}

    @app.post("/api/cloudreve/scan")
    async def trigger_cloudreve_scan(background_tasks: BackgroundTasks) -> dict[str, Any]:
        """Trigger a full recursive scan of the Cloudreve file tree.

        Returns immediately; the scan runs as a background task.  Poll
        ``/api/cloudreve/scan/status`` to follow progress.
        """
        scanner: CloudreveScanner = app.state.scanner
        if scanner.is_scanning:
            result = scanner.last_result()
            return {"status": "already_scanning", **result.to_dict()}

        # Build a lightweight delete function from the already-initialised stores.
        # Deleting knowledge data does NOT require an LLM API key.
        import logging as _log
        _del_logger = _log.getLogger(__name__)

        def _scan_delete_fn(uri: str) -> None:
            # Fetch parsed_text_key before deleting from Postgres so we can clean MinIO.
            parsed_text_key: str | None = None
            try:
                doc = repo.get_document(uri)
                if doc:
                    parsed_text_key = doc.get("parsed_text_key")
            except Exception as exc:
                _del_logger.warning("Could not fetch parsed_text_key for %s: %s", uri, exc)

            if _neo4j_store:
                try:
                    _neo4j_store.delete_file(uri)
                except Exception as exc:
                    _del_logger.warning("Neo4j delete failed for %s: %s", uri, exc)
            if _milvus_store:
                try:
                    _milvus_store.delete_chunks_by_uri(uri)
                except Exception as exc:
                    _del_logger.warning("Milvus delete failed for %s: %s", uri, exc)
            try:
                repo.delete_document(uri)
            except Exception as exc:
                _del_logger.warning("Repo delete failed for %s: %s", uri, exc)
            # Delete full-text artifact from MinIO (non-fatal).
            if parsed_text_key and parsed_text_key.startswith("s3://"):
                try:
                    _artifact_store.delete(parsed_text_key)
                except Exception as exc:
                    _del_logger.warning("MinIO artifact delete failed for %s: %s", parsed_text_key, exc)

        background_tasks.add_task(scanner.scan, delete_fn=_scan_delete_fn)
        return {"status": "started"}

    # ------------------------------------------------------------------
    # Cloudreve file-browse & download endpoints
    # ------------------------------------------------------------------

    def _get_client() -> CloudreveClient:
        return app.state.scanner.client

    @app.get("/api/cloudreve/files")
    async def cloudreve_list_files(uri: str = "cloudreve://my") -> dict[str, Any]:
        """List files/directories at *uri* (one level, non-recursive)."""
        client = _get_client()
        try:
            data = await client.list_files(uri)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"uri": uri, "data": data}

    @app.get("/api/cloudreve/files/info")
    async def cloudreve_file_info(uri: str) -> dict[str, Any]:
        """Return metadata for a single file or directory *uri*."""
        client = _get_client()
        try:
            data = await client.get_metadata(uri)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"uri": uri, "data": data}

    @app.get("/api/cloudreve/files/download")
    async def cloudreve_download_file(uri: str) -> Response:
        """Proxy-download a file from Cloudreve and return its raw bytes."""
        client = _get_client()
        try:
            content = await client.get_file_content(uri)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        filename = os.path.basename(uri.rstrip("/")) or "download"
        media_type, _ = mimetypes.guess_type(filename)
        return Response(
            content=content,
            media_type=media_type or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/cloudreve/files/upload")
    async def cloudreve_upload_file(
        file: UploadFile,
        dest_uri: str = Form(..., description="Target folder URI, e.g. cloudreve://my/reports/"),
        overwrite: bool = Form(default=True),
    ) -> dict[str, Any]:
        """Upload a local file to Cloudreve.

        Requires the OAuth token to have the ``Files.Write`` scope.
        Returns the Cloudreve session data on success.
        """
        client = _get_client()
        content = await file.read()
        filename = file.filename or "upload"
        mime_type = file.content_type or "application/octet-stream"
        try:
            data = await client.upload_file(
                content, filename, dest_uri,
                mime_type=mime_type, overwrite=overwrite,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "status": "uploaded",
            "filename": filename,
            "dest_uri": dest_uri,
            "size": len(content),
            "cloudreve": data,
        }

    return app
