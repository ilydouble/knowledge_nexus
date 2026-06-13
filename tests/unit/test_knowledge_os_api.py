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


def make_direct_client(neo4j_store):
    """Build an app wired with a specific neo4j_store (real-or-None) for delete tests."""
    app = FastAPI()
    store = InMemoryKnowledgeOSStore()
    register_knowledge_os_api(
        app,
        repository=InMemoryRepository(),
        get_store=lambda: store,
        neo4j_store=neo4j_store,
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
