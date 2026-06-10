"""Compatibility exports for the old flat Knowledge OS service path."""

from knowledge_os.application.services import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)

__all__ = [
    "CandidateExtractionService",
    "CandidateReviewService",
    "EvidenceService",
    "GraphCommitService",
]
