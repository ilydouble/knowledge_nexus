from __future__ import annotations

from nexus.models import GraphEdge, GraphNode, IngestionJob, KnowledgeLink, SemanticDocument


class InMemoryRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, IngestionJob] = {}
        self.links: dict[str, KnowledgeLink] = {}
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self.documents: dict[str, SemanticDocument] = {}

    def add_job(self, job: IngestionJob) -> IngestionJob:
        self.jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> IngestionJob | None:
        return self.jobs.get(job_id)

    def update_job(self, job: IngestionJob) -> IngestionJob:
        self.jobs[job.id] = job
        return job

    def list_jobs(self) -> list[IngestionJob]:
        return sorted(self.jobs.values(), key=lambda job: job.created_at, reverse=True)

    def add_link(self, link: KnowledgeLink) -> KnowledgeLink:
        self.links[link.id] = link
        source_id = self._node_id_for_uri(link.source_uri)
        target_id = self._node_id_for_uri(link.target_uri)
        self.nodes.setdefault(source_id, GraphNode(id=source_id, uri=link.source_uri, label=self._label_for_uri(link.source_uri), layer=link.layer))
        self.nodes.setdefault(target_id, GraphNode(id=target_id, uri=link.target_uri, label=self._label_for_uri(link.target_uri), layer=link.layer))
        self.edges[link.id] = GraphEdge(
            id=link.id,
            source=source_id,
            target=target_id,
            relation=link.relation,
            layer=link.layer,
            owner_scope=link.owner_scope,
            source_file_uri=link.source_file_uri,
            visibility=link.visibility,
        )
        return link

    def list_links(self) -> list[KnowledgeLink]:
        return list(self.links.values())

    def graph(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        return list(self.nodes.values()), list(self.edges.values())

    def add_document(self, document: SemanticDocument) -> SemanticDocument:
        self.documents[document.uri] = document
        node_id = self._node_id_for_uri(document.uri)
        self.nodes[node_id] = GraphNode(
            id=node_id,
            uri=document.uri,
            label=self._label_for_uri(document.uri),
            summary=document.summary,
            layer=None,
            accessible=True,
            properties={
                "tags": document.tags,
                "entities": document.entities,
                "chunk_count": len(document.chunks),
            },
        )
        return document

    def get_document(self, uri: str) -> SemanticDocument | None:
        return self.documents.get(uri)

    def list_documents(self) -> list[SemanticDocument]:
        return list(self.documents.values())

    def delete_document(self, uri: str) -> None:
        """Remove a document and its graph node from the in-memory store."""
        self.documents.pop(uri, None)
        node_id = self._node_id_for_uri(uri)
        self.nodes.pop(node_id, None)
        # Remove edges that reference this file node
        self.edges = {
            eid: e for eid, e in self.edges.items()
            if e.source != node_id and e.target != node_id
        }

    @staticmethod
    def _node_id_for_uri(uri: str) -> str:
        return "file:" + uri

    @staticmethod
    def _label_for_uri(uri: str) -> str:
        return uri.rsplit("/", 1)[-1] or uri
