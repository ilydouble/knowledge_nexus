from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class KnowledgeLayer(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class SyncRequest(BaseModel):
    uri: str
    requested_by: str = "system"


class IngestionJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    uri: str
    requested_by: str
    status: str = "pending"
    stage: str = "queued"
    attempts: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error: str | None = None


class LinkCreate(BaseModel):
    source_uri: str
    target_uri: str
    relation: str
    created_by: str
    layer: KnowledgeLayer = KnowledgeLayer.L3
    visibility: str | None = None
    owner_scope: str | None = None
    note: str | None = None


class KnowledgeLink(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_uri: str
    target_uri: str
    relation: str
    layer: KnowledgeLayer
    owner_scope: str
    source_file_uri: str
    visibility: str
    created_by: str
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphNode(BaseModel):
    id: str
    uri: str | None
    label: str
    summary: str | None = None
    layer: KnowledgeLayer | None = None
    accessible: bool = True
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str
    layer: KnowledgeLayer
    owner_scope: str
    source_file_uri: str
    visibility: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphResult(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    hidden_node_count: int = 0


class SemanticSearchRequest(BaseModel):
    query: str
    requested_by: str
    layers: list[KnowledgeLayer] = Field(default_factory=lambda: [KnowledgeLayer.L1, KnowledgeLayer.L2, KnowledgeLayer.L3])


class GraphRagRequest(BaseModel):
    question: str
    requested_by: str
    layers: list[KnowledgeLayer] = Field(default_factory=lambda: [KnowledgeLayer.L1, KnowledgeLayer.L2, KnowledgeLayer.L3])


class GraphRagAnswer(BaseModel):
    answer: str
    citations: list[GraphNode] = Field(default_factory=list)
    hidden_node_count: int = 0


class TextChunk(BaseModel):
    id: str
    text: str
    index: int


class SemanticDocument(BaseModel):
    uri: str
    summary: str
    tags: list[str]
    entities: list[str]
    chunks: list[TextChunk]
    requested_by: str


class LinkSuggestion(BaseModel):
    source_uri: str
    target_uri: str
    relation: str = "RELATED_TO"
    layer: KnowledgeLayer = KnowledgeLayer.L3
    reason: str
    score: float
