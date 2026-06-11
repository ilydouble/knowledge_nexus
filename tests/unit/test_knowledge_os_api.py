from urllib.parse import quote

from fastapi.testclient import TestClient

from core.app_factory import create_application
from core.repositories.memory import InMemoryRepository


def make_client():
    return TestClient(create_application(repository=InMemoryRepository()))


def test_admin_candidate_api_supports_extract_review_preview_commit_and_evidence():
    client = make_client()

    extract_response = client.post(
        "/api/admin/candidates/extract",
        json={
            "uri": "cloudreve://my/design.md",
            "requested_by": "pi-agent",
            "template_ids": ["nexus/technical_doc"],
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
