"""Knowledge OS candidate governance kernel.

Canonical package layout:
- ``domain``: Pydantic models and status vocabulary.
- ``application``: use-case services for extract/review/preview/commit/governance.
- ``infrastructure``: persistence adapters and store protocols.

The old flat modules (``models``, ``services``, ``store``, ``postgres_store``)
remain as compatibility shims while the wider codebase migrates.
"""

from nexus.knowledge_os.application import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from nexus.knowledge_os.domain import (
    CandidateBatch,
    CandidateEdit,
    CandidateExtractionRequest,
    CandidateGraphItem,
    CandidateOntology,
    GraphEvidence,
)
from nexus.knowledge_os.infrastructure import (
    InMemoryKnowledgeOSStore,
    KnowledgeOSStore,
    PostgresKnowledgeOSStore,
)

__all__ = [
    "CandidateBatch",
    "CandidateEdit",
    "CandidateExtractionRequest",
    "CandidateExtractionService",
    "CandidateGraphItem",
    "CandidateOntology",
    "CandidateReviewService",
    "EvidenceService",
    "GraphCommitService",
    "GraphEvidence",
    "InMemoryKnowledgeOSStore",
    "KnowledgeOSStore",
    "PostgresKnowledgeOSStore",
]
