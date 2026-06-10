"""Knowledge OS candidate governance kernel.

Canonical package layout:
- ``domain``: Pydantic models and status vocabulary.
- ``application``: use-case services for extract/review/preview/commit/governance.
- ``infrastructure``: persistence adapters and store protocols.

Flat modules (``models``, ``services``, ``store``, ``postgres_store``) remain
as convenience shims. The old ``nexus.knowledge_os`` package forwards here for
backward compatibility.
"""

from knowledge_os.application import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from knowledge_os.domain import (
    CandidateBatch,
    CandidateEdit,
    CandidateExtractionRequest,
    CandidateGraphItem,
    CandidateOntology,
    GraphEvidence,
)
from knowledge_os.infrastructure import (
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
