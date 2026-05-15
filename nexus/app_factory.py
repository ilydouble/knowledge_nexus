from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from nexus.models import GraphRagRequest, LinkCreate, SemanticSearchRequest, SyncRequest
from nexus.repositories.base import NexusRepository
from nexus.repositories.memory import InMemoryRepository
from nexus.repositories.postgres import PostgresRepository
from nexus.services.autolinker import AutoLinker
from nexus.services.graphrag import GraphRagService
from nexus.services.ingestion import IngestionService
from nexus.services.links import LinkService
from nexus.services.permissions import PermissionFilter
from nexus.services.pipeline import SemanticPipeline
from nexus.services.semantic import SemanticProcessor
from nexus.settings import Settings


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

    def get_repository() -> NexusRepository:
        return repo

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/auth/cloudreve/bind")
    def bind_cloudreve(payload: dict[str, str]) -> dict[str, str]:
        token = payload.get("token")
        if not token:
            raise HTTPException(status_code=400, detail="token is required")
        return {"status": "bound"}

    @app.post("/api/ingestion/sync")
    def sync(request: SyncRequest, process: bool = False, repository: NexusRepository = Depends(get_repository)):
        ingestion = IngestionService(repository)
        job = ingestion.sync(request)
        if not process:
            return job
        ingestion.mark_running(job.id)
        result = SemanticPipeline(
            cloudreve_token=app_settings.cloudreve_token,
            settings=app_settings,
            repository=repository,
            enable_neo4j=bool(app_settings.neo4j_uri),
            enable_milvus=bool(app_settings.milvus_host),
        ).process_file(uri=request.uri, requested_by=request.requested_by)
        if result.success:
            job = ingestion.mark_succeeded(job.id)
        else:
            job = ingestion.mark_failed(job.id, result.error or "processing failed")
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

    @app.post("/api/search/semantic")
    def semantic_search(request: SemanticSearchRequest, repository: NexusRepository = Depends(get_repository)):
        nodes, edges = repository.graph()
        result = permission_filter.filter_graph([node for node in nodes if request.query.lower() in node.label.lower()], edges)
        return {"query": request.query, "results": result.nodes, "hidden_node_count": result.hidden_node_count}

    @app.post("/api/graphrag/ask")
    def graphrag_ask(request: GraphRagRequest, repository: NexusRepository = Depends(get_repository)):
        return GraphRagService(repository, permission_filter).ask(request)

    return app
