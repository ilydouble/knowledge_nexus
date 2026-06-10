from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


CandidateStatus = str


def _now() -> datetime:
    return datetime.now(UTC)


class CandidateExtractionRequest(BaseModel):
    uri: str
    requested_by: str = "pi-agent"
    instructions: str | None = None
    parent_batch_id: str | None = None
    template_ids: list[str] = Field(default_factory=list)
    candidate_entities: list[dict[str, Any]] = Field(default_factory=list)
    candidate_relations: list[dict[str, Any]] = Field(default_factory=list)
    candidate_ontology: dict[str, Any] | None = None


class CandidateBatch(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_uri: str
    requested_by: str
    status: CandidateStatus = "candidate"
    template_ids: list[str] = Field(default_factory=list)
    instructions: str | None = None
    parent_batch_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    committed_at: datetime | None = None


class CandidateOntology(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    batch_id: str
    name: str
    schema_payload: dict[str, Any] = Field(alias="schema")
    status: CandidateStatus = "candidate"
    confidence: float = 0.8
    review_note: str | None = None


class CandidateGraphItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    batch_id: str
    kind: str  # node | edge
    payload: dict[str, Any]
    source_span: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.8
    status: CandidateStatus = "candidate"
    review_note: str | None = None


class GraphEvidence(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    graph_item_id: str
    source_uri: str
    batch_id: str
    template_id: str | None = None
    evidence_text: str | None = None
    confidence: float = 0.8
    status: str = "active"
    created_at: datetime = Field(default_factory=_now)


class CandidateEdit(BaseModel):
    item_id: str
    status: CandidateStatus | None = None
    payload: dict[str, Any] | None = None
    review_note: str | None = None


class GraphChangePreview(BaseModel):
    batch_id: str
    source_uri: str
    summary: dict[str, int]
    changes: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


class CommitResult(BaseModel):
    batch_id: str
    status: str
    committed_items: int
    skipped_items: int
    evidence_created: int
    warnings: list[str] = Field(default_factory=list)
