from fastapi.testclient import TestClient

from nexus.api import create_app


def test_health_endpoint_reports_service_status():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sync_endpoint_creates_job():
    client = TestClient(create_app())

    response = client.post(
        "/api/ingestion/sync",
        json={"uri": "cloudreve://my/demo.md", "requested_by": "user-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["uri"] == "cloudreve://my/demo.md"


def test_sync_endpoint_can_process_file_through_pipeline(monkeypatch):
    seen = {}

    class FakePipeline:
        def __init__(self, *, cloudreve_token, settings, repository, enable_neo4j, enable_milvus):
            seen["repository"] = repository
            seen["settings"] = settings
            seen["enable_neo4j"] = enable_neo4j
            seen["enable_milvus"] = enable_milvus

        def process_file(self, uri, requested_by):
            seen["uri"] = uri
            seen["requested_by"] = requested_by

            class Result:
                success = True
                summary = "processed"
                tags = ["demo"]
                entities_count = 1
                relations_count = 0
                chunks_count = 2
                error = None
                processing_time_ms = 12

            return Result()

    monkeypatch.setattr("nexus.app_factory.SemanticPipeline", FakePipeline)
    client = TestClient(create_app())

    response = client.post(
        "/api/ingestion/sync?process=true",
        json={"uri": "cloudreve://my/demo.md", "requested_by": "user-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "pending"
    assert body["processing"]["success"] is True
    assert seen["uri"] == "cloudreve://my/demo.md"
    assert seen["requested_by"] == "user-1"


def test_graphrag_answer_does_not_include_inaccessible_content():
    client = TestClient(create_app())
    client.post("/api/links", json={
        "source_uri": "cloudreve://my/public.md",
        "target_uri": "cloudreve://other/secret.md",
        "relation": "RELATED_TO",
        "created_by": "user-1",
    })

    response = client.post(
        "/api/graphrag/ask",
        json={"question": "What is related?", "requested_by": "user-1", "layers": ["L3"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert "Secret" not in body["answer"]
    assert body["hidden_node_count"] >= 0


def test_demo_index_endpoint_populates_file_knowledge_and_suggestions():
    client = TestClient(create_app())
    client.post(
        "/api/ingestion/demo-index",
        json={
            "uri": "cloudreve://my/a.md",
            "content": "Infrared sensor thermal calibration.",
            "requested_by": "user-1",
        },
    )
    client.post(
        "/api/ingestion/demo-index",
        json={
            "uri": "cloudreve://my/b.md",
            "content": "Thermal sensor project notes.",
            "requested_by": "user-1",
        },
    )

    response = client.get("/api/files/knowledge", params={"uri": "cloudreve://my/a.md"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Infrared sensor thermal calibration."
    assert "infrared" in body["tags"]
    assert body["suggestions"][0]["target_uri"] == "cloudreve://my/b.md"
