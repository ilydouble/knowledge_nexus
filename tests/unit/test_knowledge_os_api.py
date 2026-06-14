import json
from unittest.mock import MagicMock
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.factory import create_application
from knowledge_os.application.extraction_pipeline import ExtractionInputError
from knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from knowledge_os.interfaces.api import register_knowledge_os_api
from core.repositories.memory import InMemoryRepository


def make_client():
    return TestClient(create_application(repository=InMemoryRepository()))


def make_direct_client(neo4j_store, milvus_store=None, artifact_store=None, repository=None):
    """Build an app wired with specific stores for delete/content tests."""
    app = FastAPI()
    store = InMemoryKnowledgeOSStore()
    repo = repository or InMemoryRepository()
    register_knowledge_os_api(
        app,
        repository=repo,
        get_store=lambda: store,
        neo4j_store=neo4j_store,
        milvus_store=milvus_store,
        artifact_store=artifact_store,
    )
    return TestClient(app)


def test_admin_candidate_api_supports_extract_review_preview_commit_and_evidence():
    client = make_client()

    extract_response = client.post(
        "/api/admin/candidates/extract",
        json={
            "uri": "cloudreve://my/design.md",
            "requested_by": "pi-agent",
            "template_ids": ["general/base_graph"],
            "candidate_entities": [{"id": "api", "label": "API", "type": "Component"}],
            "candidate_relations": [
                {
                    "source": "api",
                    "target": "postgres",
                    "relation": "STORES_IN",
                    "evidence": "API stores data in Postgres.",
                }
            ],
        },
    )
    assert extract_response.status_code == 200
    batch_id = extract_response.json()["batch"]["id"]
    relation_item = next(item for item in extract_response.json()["graph_items"] if item["kind"] == "edge")

    patch_response = client.patch(
        f"/api/admin/candidates/{batch_id}",
        json={"edits": [{"item_id": relation_item["id"], "status": "accepted"}]},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["updated"][0]["status"] == "accepted"

    preview_response = client.post(f"/api/admin/candidates/{batch_id}/preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["changes"][0]["action"] == "create_edge"

    commit_response = client.post(f"/api/admin/candidates/{batch_id}/commit")
    assert commit_response.status_code == 200
    assert commit_response.json()["committed_items"] == 1

    evidence_response = client.get(
        "/api/admin/graph/evidence",
        params={"graph_item_id": "edge:api:STORES_IN:postgres"},
    )
    assert evidence_response.status_code == 200
    assert evidence_response.json()["evidence"][0]["source_uri"] == "cloudreve://my/design.md"

    encoded_uri = quote("cloudreve://my/design.md", safe="")
    deleted_response = client.post(f"/api/admin/documents/{encoded_uri}/mark-source-deleted")
    assert deleted_response.status_code == 200
    assert deleted_response.json()["evidence_marked_stale"] == 1


def test_delete_graph_endpoint_hard_deletes_neo4j_and_purges_evidence():
    neo4j = MagicMock()
    neo4j.delete_file = MagicMock(return_value=None)
    client = make_direct_client(neo4j)

    encoded_uri = quote("cloudreve://my/report.md", safe="")
    response = client.delete(f"/api/admin/documents/{encoded_uri}/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["deleted_uri"] == "cloudreve://my/report.md"
    assert body["neo4j"] == "nodes and edges removed"
    neo4j.delete_file.assert_called_once_with("cloudreve://my/report.md")


def test_delete_graph_endpoint_returns_503_when_neo4j_unavailable():
    client = make_direct_client(None)

    encoded_uri = quote("cloudreve://my/report.md", safe="")
    response = client.delete(f"/api/admin/documents/{encoded_uri}/graph")

    assert response.status_code == 503
    assert "Neo4j" in response.json()["detail"]


def make_pipeline_client(pipeline):
    """Build an app whose extraction pipeline is a caller-supplied mock."""
    app = FastAPI()
    store = InMemoryKnowledgeOSStore()
    register_knowledge_os_api(
        app,
        repository=InMemoryRepository(),
        get_store=lambda: store,
        get_extraction_pipeline=lambda: pipeline,
    )
    return TestClient(app)


def test_extract_file_maps_input_error_to_400():
    """A gate rejection (ExtractionInputError) is a user error → HTTP 400."""
    pipeline = MagicMock()
    pipeline.run.side_effect = ExtractionInputError("File skipped by gate: binary/media file")
    client = make_pipeline_client(pipeline)

    response = client.post(
        "/api/admin/candidates/extract/file",
        files={"file": ("photo.jpg", b"binary", "image/jpeg")},
    )

    assert response.status_code == 400
    assert "skipped by gate" in response.json()["detail"]


def test_extract_file_maps_llm_parse_error_to_500():
    """An internal JSONDecodeError (a ValueError subclass) must surface as 500."""
    pipeline = MagicMock()
    pipeline.run.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    client = make_pipeline_client(pipeline)

    response = client.post(
        "/api/admin/candidates/extract/file",
        files={"file": ("report.md", b"# report", "text/markdown")},
    )

    assert response.status_code == 500
    assert "Extraction failed" in response.json()["detail"]


# ── /api/admin/documents/content tests ───────────────────────────────────────

class _MockRepo(InMemoryRepository):
    """Extends InMemoryRepository so get_document() can return arbitrary data."""

    def __init__(self, doc_data=None):
        super().__init__()
        self._doc_data = doc_data or {}

    def get_document(self, uri: str):  # type: ignore[override]
        return self._doc_data.get(uri)


def test_content_endpoint_returns_410_for_cloudreve_key():
    """parsed_text_key with cloudreve:// scheme should return 410 (provenance only)."""
    uri = "local:///docs/report.pdf"
    repo = _MockRepo({uri: {"parsed_text_key": "cloudreve://my/docs/report.pdf"}})
    client = make_direct_client(neo4j_store=None, repository=repo)

    response = client.get("/api/admin/documents/content", params={"uri": uri})

    assert response.status_code == 410
    detail = response.json()["detail"]
    assert "cloudreve" in detail.lower()


def test_content_endpoint_returns_404_for_unknown_document():
    """When the document is not in the repository, expect 404."""
    client = make_direct_client(neo4j_store=None)
    response = client.get("/api/admin/documents/content", params={"uri": "local:///no/such.pdf"})
    assert response.status_code == 404


def test_content_endpoint_returns_422_for_missing_key():
    """Document exists but has no parsed_text_key → 422."""
    uri = "local:///docs/empty.pdf"
    repo = _MockRepo({uri: {"parsed_text_key": None}})
    client = make_direct_client(neo4j_store=None, repository=repo)

    response = client.get("/api/admin/documents/content", params={"uri": uri})
    assert response.status_code == 422


def test_content_endpoint_reads_from_artifact_store_for_s3_key():
    """s3:// key + artifact_store configured → returns text from object storage."""
    uri = "local:///docs/report.pdf"
    s3_key = "s3://knowledge-nexus/parsed-text/abcd/report.txt"
    repo = _MockRepo({uri: {"parsed_text_key": s3_key}})
    artifact = MagicMock()
    artifact.read.return_value = "Full document text from MinIO."
    client = make_direct_client(neo4j_store=None, artifact_store=artifact, repository=repo)

    response = client.get("/api/admin/documents/content", params={"uri": uri})

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "object_storage"
    assert data["text"] == "Full document text from MinIO."
    artifact.read.assert_called_once_with(s3_key)


# ── DELETE /api/admin/documents/{uri}/graph with Milvus+MinIO cleanup ─────────

def test_delete_graph_also_cleans_milvus():
    """Hard delete via API should invoke milvus_store.delete_chunks_by_uri."""
    neo4j = MagicMock()
    milvus = MagicMock()
    uri = "local:///docs/report.pdf"
    repo = _MockRepo({uri: {"parsed_text_key": "local:///docs/report.pdf"}})
    client = make_direct_client(neo4j_store=neo4j, milvus_store=milvus, repository=repo)

    encoded = quote(uri, safe="")
    response = client.delete(f"/api/admin/documents/{encoded}/graph")

    assert response.status_code == 200
    milvus.delete_chunks_by_uri.assert_called_once_with(uri)
    assert "chunks deleted" in response.json()["milvus"]


def test_delete_graph_cleans_minio_artifact_when_s3_key():
    """Hard delete should call artifact_store.delete when parsed_text_key is s3://."""
    neo4j = MagicMock()
    artifact = MagicMock()
    uri = "local:///docs/report.pdf"
    s3_key = "s3://knowledge-nexus/parsed-text/abcd/report.txt"
    repo = _MockRepo({uri: {"parsed_text_key": s3_key}})
    client = make_direct_client(neo4j_store=neo4j, artifact_store=artifact, repository=repo)

    encoded = quote(uri, safe="")
    response = client.delete(f"/api/admin/documents/{encoded}/graph")

    assert response.status_code == 200
    artifact.delete.assert_called_once_with(s3_key)
    assert response.json()["artifact"] == "deleted"


def test_delete_graph_cleans_local_artifact_when_local_key():
    """Hard delete should call artifact_store.delete when parsed_text_key is local://."""
    neo4j = MagicMock()
    artifact = MagicMock()
    uri = "local:///docs/report.pdf"
    local_key = "local:///app/data/artifacts/parsed-text/abcd1234/report.pdf.txt"
    repo = _MockRepo({uri: {"parsed_text_key": local_key}})
    client = make_direct_client(neo4j_store=neo4j, artifact_store=artifact, repository=repo)

    encoded = quote(uri, safe="")
    response = client.delete(f"/api/admin/documents/{encoded}/graph")

    assert response.status_code == 200
    artifact.delete.assert_called_once_with(local_key)
    assert response.json()["artifact"] == "deleted"


def test_delete_graph_artifact_skipped_when_no_artifact_key():
    """When parsed_text_key is absent, artifact delete should be skipped cleanly."""
    neo4j = MagicMock()
    artifact = MagicMock()
    uri = "local:///docs/report.pdf"
    repo = _MockRepo({uri: {"parsed_text_key": None}})
    client = make_direct_client(neo4j_store=neo4j, artifact_store=artifact, repository=repo)

    encoded = quote(uri, safe="")
    response = client.delete(f"/api/admin/documents/{encoded}/graph")

    assert response.status_code == 200
    artifact.delete.assert_not_called()
    assert "skipped" in response.json()["artifact"]
