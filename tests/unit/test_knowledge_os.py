from knowledge_os.application.services import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from knowledge_os.domain.models import CandidateEdit, CandidateExtractionRequest
from knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from core.repositories.memory import InMemoryRepository


def test_candidate_lifecycle_previews_and_commits_only_accepted_items():
    store = InMemoryKnowledgeOSStore()
    repository = InMemoryRepository()
    extraction = CandidateExtractionService(store)
    review = CandidateReviewService(store)
    committer = GraphCommitService(store, repository=repository)

    batch = extraction.run(
        CandidateExtractionRequest(
            uri="cloudreve://my/design.md",
            requested_by="pi-agent",
            instructions="extract architecture graph",
            candidate_entities=[
                {"id": "svc-api", "label": "API Service", "type": "Component", "confidence": 0.91},
                {"id": "db-main", "label": "Main DB", "type": "Database", "confidence": 0.83},
            ],
            candidate_relations=[
                {
                    "source": "svc-api",
                    "target": "db-main",
                    "relation": "STORES_IN",
                    "evidence": "API Service stores profiles in Main DB.",
                    "confidence": 0.88,
                }
            ],
            template_ids=["nexus/technical_doc"],
        )
    )

    graph_items = store.list_candidate_graph_items(batch.id)
    relation_item = next(item for item in graph_items if item.kind == "edge")
    rejected_item = next(item for item in graph_items if item.payload.get("id") == "db-main")
    review.apply_edits(
        batch.id,
        [
            CandidateEdit(item_id=relation_item.id, status="accepted", review_note="looks right"),
            CandidateEdit(item_id=rejected_item.id, status="rejected", review_note="too generic"),
        ],
    )

    preview = committer.preview(batch.id)
    assert preview.batch_id == batch.id
    assert preview.summary["accepted_items"] == 1
    assert preview.summary["rejected_items"] == 1
    assert preview.changes[0]["action"] == "create_edge"
    assert preview.changes[0]["relation"] == "STORES_IN"

    result = committer.commit(batch.id)
    assert result.status == "committed"
    assert result.committed_items == 1
    assert result.skipped_items == 2
    assert len(store.list_graph_evidence(source_uri="cloudreve://my/design.md")) == 1

    second_result = committer.commit(batch.id)
    assert second_result.status == "committed"
    assert second_result.committed_items == 0
    assert second_result.skipped_items == 3


def test_source_deleted_marks_document_and_evidence_stale_without_purging_graph():
    store = InMemoryKnowledgeOSStore()
    repository = InMemoryRepository()
    extraction = CandidateExtractionService(store)
    review = CandidateReviewService(store)
    committer = GraphCommitService(store, repository=repository)
    evidence = EvidenceService(store, repository=repository)

    batch = extraction.run(
        CandidateExtractionRequest(
            uri="cloudreve://my/report.md",
            requested_by="pi-agent",
            candidate_entities=[{"id": "risk", "label": "Risk", "type": "Concept"}],
        )
    )
    item = store.list_candidate_graph_items(batch.id)[0]
    review.apply_edits(batch.id, [CandidateEdit(item_id=item.id, status="accepted")])
    committer.commit(batch.id)

    outcome = evidence.mark_source_deleted("cloudreve://my/report.md")

    assert outcome["uri"] == "cloudreve://my/report.md"
    assert outcome["evidence_marked_stale"] == 1
    assert store.get_document_status("cloudreve://my/report.md") == "source_deleted"
    assert store.list_graph_evidence(source_uri="cloudreve://my/report.md")[0].status == "stale"
