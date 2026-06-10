from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from pydantic import BaseModel

from nexus.cloudreve.client import CloudreveClient
from nexus.cloudreve.oauth import (
    CloudreveOAuthConfigStore,
    CloudreveOAuthError,
    CloudreveOAuthTokenStore,
    build_authorization_url,
    exchange_authorization_code,
    refresh_oauth_tokens,
    resolve_oauth_settings,
)
from nexus.graph.neo4j_store import Neo4jGraphStore
from nexus.knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from nexus.knowledge_os.infrastructure.postgres_store import PostgresKnowledgeOSStore
from nexus.knowledge_os.infrastructure.store import KnowledgeOSStore
from nexus.knowledge_os.interfaces.api import register_knowledge_os_api
from nexus.models import GraphRagRequest, KnowledgeLayer, LinkCreate, SemanticSearchRequest, SyncRequest
from nexus.repositories.base import NexusRepository
from nexus.repositories.memory import InMemoryRepository
from nexus.repositories.postgres import PostgresRepository
from nexus.services.autolinker import AutoLinker
from nexus.services.doc_linker import DocLinker
from nexus.services.scanner import CloudreveScanner
from nexus.services.graphrag import GraphRagService
from nexus.services.ingestion import IngestionService
from nexus.services.links import LinkService
from nexus.services.permissions import PermissionFilter
from nexus.services.embedding import BigModelEmbeddingService, DeterministicEmbeddingService
from nexus.services.pipeline import SemanticPipeline
from nexus.services.semantic import SemanticProcessor
from nexus.settings import Settings
from nexus.vector.milvus_store import MilvusVectorStore


class GraphAskRequest(BaseModel):
    question: str
    requested_by: str = "system"


def _processing_result_to_dict(result: Any) -> dict[str, Any]:
    if is_dataclass(result):
        return asdict(result)
    result_dict = getattr(result, "__dict__", None)
    if result_dict:
        return dict(result_dict)
    keys = [
        "success",
        "summary",
        "tags",
        "entities_count",
        "relations_count",
        "chunks_count",
        "error",
        "processing_time_ms",
    ]
    return {key: getattr(result, key) for key in keys if hasattr(result, key)}


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
    app = FastAPI(title="Knowledge Nexus API", version="0.1.0")
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
    permission_filter = PermissionFilter()
    app.state.settings = app_settings
    app.state.repository = repo
    app.state.scanner = CloudreveScanner(CloudreveClient(), repo)
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
            from nexus.agents.graph_qa_agent import create_graph_qa_agent  # lazy
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

    @app.post("/api/ingestion/sync")
    def sync(request: SyncRequest, process: bool = False, repository: NexusRepository = Depends(get_repository)):
        ingestion = IngestionService(repository)
        job = ingestion.sync(request)
        if not process:
            return job
        return _process_job(job.id, repository)

    @app.get("/api/ingestion/files")
    def list_ingestion_files(repository: NexusRepository = Depends(get_repository)):
        return IngestionService(repository).list_files()

    @app.post("/api/ingestion/files/retry")
    def retry_file(payload: dict[str, str], repository: NexusRepository = Depends(get_repository)):
        uri = payload.get("uri")
        if not uri:
            raise HTTPException(status_code=400, detail="uri is required")
        requested_by = payload.get("requested_by") or "system"
        job = IngestionService(repository).sync(SyncRequest(uri=uri, requested_by=requested_by))
        return _process_job(job.id, repository)

    @app.post("/api/ingestion/jobs/{job_id}/retry")
    def retry_job(job_id: str, repository: NexusRepository = Depends(get_repository)):
        if repository.get_job(job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _process_job(job_id, repository)

    def _process_job(job_id: str, repository: NexusRepository) -> dict[str, Any]:
        ingestion = IngestionService(repository)
        job = ingestion.mark_running(job_id)
        ingestion.mark_stage(job.id, "download")
        result = SemanticPipeline(
            cloudreve_token=None,
            settings=app_settings,
            repository=repository,
            enable_neo4j=bool(app_settings.neo4j_uri),
            enable_milvus=bool(app_settings.milvus_host),
        ).process_file(uri=job.uri, requested_by=job.requested_by)
        if result.success:
            job = ingestion.mark_succeeded(job.id)
        else:
            job = ingestion.mark_failed(
                job.id,
                result.error or "processing failed",
                stage=getattr(result, "stage", None) or "download",
                error_code=getattr(result, "error_code", None),
            )
        return {"job": job, "processing": _processing_result_to_dict(result)}

    @app.get("/api/ingestion/jobs")
    def list_jobs(repository: NexusRepository = Depends(get_repository)):
        return IngestionService(repository).list_jobs()

    @app.get("/api/documents")
    def list_documents(repository: NexusRepository = Depends(get_repository)):
        documents = repository.list_documents()
        return [
            {
                "uri": document.uri,
                "summary": document.summary,
                "tags": document.tags,
                "entities": document.entities,
                "chunk_count": len(document.chunks),
                "requested_by": document.requested_by,
            }
            for document in documents
        ]

    @app.post("/api/documents/link")
    def link_documents(
        min_shared_entities: int = 1,
        repository: NexusRepository = Depends(get_repository),
    ) -> dict[str, Any]:
        results = DocLinker(repository=repository, settings=app_settings).find_and_link_all(
            min_shared_entities=max(1, min_shared_entities)
        )
        return {
            "created_count": len(results),
            "links": [
                {
                    "source_uri": result.uri_a,
                    "target_uri": result.uri_b,
                    "relation": result.relation,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning,
                    "shared_entities": result.shared_entities,
                    "direction": result.direction,
                }
                for result in results
            ],
        }

    @app.post("/api/ingestion/demo-index")
    def demo_index(payload: dict[str, str], repository: NexusRepository = Depends(get_repository)):
        uri = payload.get("uri")
        content = payload.get("content")
        requested_by = payload.get("requested_by") or "system"
        if not uri or content is None:
            raise HTTPException(status_code=400, detail="uri and content are required")
        return SemanticProcessor(repository).index_text(uri=uri, content=content, requested_by=requested_by)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, repository: NexusRepository = Depends(get_repository)):
        job = repository.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/links")
    def create_link(request: LinkCreate, repository: NexusRepository = Depends(get_repository)):
        return LinkService(repository).create_link(request)

    @app.get("/api/files/knowledge")
    def file_knowledge(uri: str, repository: NexusRepository = Depends(get_repository)):
        links = [link for link in repository.list_links() if link.source_uri == uri or link.target_uri == uri]
        document = repository.get_document(uri)
        return {
            "uri": uri,
            "summary": document.summary if document else None,
            "tags": document.tags if document else [],
            "entities": document.entities if document else [],
            "relations": links,
            "suggestions": AutoLinker(repository).suggest(uri),
        }

    @app.get("/api/graph/neighborhood")
    def graph_neighborhood(repository: NexusRepository = Depends(get_repository)):
        nodes, edges = repository.graph()
        return permission_filter.filter_graph(nodes, edges)

    @app.get("/api/graph")
    def get_graph(uri: str | None = None):
        """Return the Neo4j knowledge graph.

        - Without ``uri``: return the full graph (all nodes and edges).
        - With ``uri``: return the 1-hop neighborhood of the given document.
        """
        if _neo4j_store is None:
            return {"nodes": [], "edges": [], "hidden_node_count": 0, "error": "Neo4j not configured"}
        all_layers = [KnowledgeLayer.L1, KnowledgeLayer.L2, KnowledgeLayer.L3]
        if uri:
            result = _neo4j_store.neighborhood(uri, layers=all_layers)
        else:
            result = _neo4j_store.full_graph()
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
        from nexus.agents.graph_qa_agent import ask as agent_ask
        answer = agent_ask(request.question, _graph_qa_agent)
        return {"question": request.question, "answer": answer}

    @app.post("/api/search/semantic")
    def semantic_search(request: SemanticSearchRequest, repository: NexusRepository = Depends(get_repository)):
        nodes, edges = repository.graph()
        result = permission_filter.filter_graph([node for node in nodes if request.query.lower() in node.label.lower()], edges)
        return {"query": request.query, "results": result.nodes, "hidden_node_count": result.hidden_node_count}

    @app.post("/api/graphrag/ask")
    def graphrag_ask(request: GraphRagRequest, repository: NexusRepository = Depends(get_repository)):
        return GraphRagService(repository, permission_filter).ask(request)

    register_knowledge_os_api(app, repository=repo, get_store=get_knowledge_os_store)

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

        background_tasks.add_task(scanner.scan, delete_fn=_scan_delete_fn)
        return {"status": "started"}

    return app
