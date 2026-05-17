from __future__ import annotations

from nexus.models import KnowledgeLayer, KnowledgeLink, LinkCreate
from nexus.repository import InMemoryRepository


class LinkService:
    def __init__(self, repository: InMemoryRepository) -> None:
        self.repository = repository

    def create_link(self, request: LinkCreate) -> KnowledgeLink:
        visibility = request.visibility
        if visibility is None:
            visibility = "private" if request.layer == KnowledgeLayer.L3 else "team"
        owner_scope = request.owner_scope
        if owner_scope is None:
            owner_scope = f"user:{request.created_by}" if request.layer == KnowledgeLayer.L3 else "team:default"
        link = KnowledgeLink(
            source_uri=request.source_uri,
            target_uri=request.target_uri,
            relation=request.relation,
            layer=request.layer,
            owner_scope=owner_scope,
            source_file_uri=request.source_uri,
            visibility=visibility,
            created_by=request.created_by,
            note=request.note,
        )
        return self.repository.add_link(link)

