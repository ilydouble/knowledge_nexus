from fastapi.testclient import TestClient

from nexus.api import create_app
from nexus.repositories.memory import InMemoryRepository
from nexus.settings import Settings


def make_client(settings=None):
    return TestClient(create_app(repository=InMemoryRepository(), settings=settings))


def test_health_endpoint_reports_service_status():
    client = make_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_allows_local_web_console_cors_preflight():
    client = make_client()

    response = client.options(
        "/api/documents",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cloudreve_oauth_start_redirects_to_authorization_endpoint():
    settings = Settings(
        cloudreve_base_url="http://cloudreve.local",
        cloudreve_oauth_client_id="client-id",
        cloudreve_oauth_client_secret="client-secret",
        cloudreve_oauth_redirect_uri="http://localhost:8000/api/auth/cloudreve/callback",
    )
    client = make_client(settings=settings)

    response = client.get("/api/auth/cloudreve/start", follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("http://cloudreve.local/session/authorize?")
    assert "response_type=code" in location
    assert "client_id=client-id" in location
    assert "offline_access" in location


def test_cloudreve_oauth_status_reports_token_store_state(tmp_path):
    settings = Settings(cloudreve_token_store_path=str(tmp_path / "tokens.json"))
    client = make_client(settings=settings)

    response = client.get("/api/auth/cloudreve/status")

    assert response.status_code == 200
    assert response.json() == {"authorized": False}


def test_cloudreve_oauth_config_can_be_saved_and_used_for_authorization(tmp_path):
    settings = Settings(cloudreve_oauth_config_path=str(tmp_path / "oauth_config.json"))
    client = make_client(settings=settings)

    config_response = client.post(
        "/api/auth/cloudreve/config",
        json={
            "cloudreve_base_url": "http://cloudreve.local",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "http://localhost:8000/api/auth/cloudreve/callback",
            "scope": "offline_access",
        },
    )
    start_response = client.get("/api/auth/cloudreve/start", follow_redirects=False)

    assert config_response.status_code == 200
    assert config_response.json()["configured"] is True
    assert start_response.status_code == 307
    assert start_response.headers["location"].startswith("http://cloudreve.local/session/authorize?")


def test_cloudreve_oauth_start_reports_setup_required_when_config_missing(tmp_path):
    settings = Settings(cloudreve_oauth_config_path=str(tmp_path / "missing.json"))
    client = make_client(settings=settings)

    response = client.get("/api/auth/cloudreve/start", follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "oauth_config_required"


def test_cloudreve_oauth_status_refreshes_token_before_reporting_authorized(monkeypatch, tmp_path):
    token_path = tmp_path / "tokens.json"
    token_path.write_text('{"access_token":"expired","refresh_token":"refresh-token"}', encoding="utf-8")
    settings = Settings(cloudreve_base_url="http://cloudreve.local", cloudreve_token_store_path=str(token_path))
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"code": 0, "data": {"access_token": "fresh", "refresh_token": "fresh-refresh"}, "msg": ""}

    def fake_post(url, *, json, headers, timeout):
        seen["url"] = url
        seen["json"] = json
        return FakeResponse()

    monkeypatch.setattr("nexus.cloudreve.oauth.requests.post", fake_post)
    client = make_client(settings=settings)

    response = client.get("/api/auth/cloudreve/status")

    assert response.status_code == 200
    assert response.json()["authorized"] is True
    assert response.json()["has_refresh_token"] is True
    assert seen["url"] == "http://cloudreve.local/api/v4/session/token/refresh"
    assert seen["json"] == {"refresh_token": "refresh-token"}


def test_cloudreve_oauth_status_reports_refresh_failure(monkeypatch, tmp_path):
    token_path = tmp_path / "tokens.json"
    token_path.write_text('{"access_token":"expired","refresh_token":"expired-refresh"}', encoding="utf-8")
    settings = Settings(cloudreve_base_url="http://cloudreve.local", cloudreve_token_store_path=str(token_path))

    class FakeResponse:
        status_code = 401

        def json(self):
            return {"code": 401, "msg": "invalid refresh token"}

    monkeypatch.setattr("nexus.cloudreve.oauth.requests.post", lambda *args, **kwargs: FakeResponse())
    client = make_client(settings=settings)

    response = client.get("/api/auth/cloudreve/status")

    assert response.status_code == 200
    assert response.json()["authorized"] is False
    assert response.json()["error"] == "refresh_failed"


def test_cloudreve_oauth_callback_exchanges_code_and_saves_tokens(monkeypatch, tmp_path):
    settings = Settings(
        cloudreve_base_url="http://cloudreve.local",
        cloudreve_oauth_client_id="client-id",
        cloudreve_oauth_client_secret="client-secret",
        cloudreve_oauth_redirect_uri="http://localhost:8000/api/auth/cloudreve/callback",
        cloudreve_token_store_path=str(tmp_path / "tokens.json"),
    )
    seen = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "refresh_token_expires_in": 7776000,
            }

    class FakeRefreshResponse:
        status_code = 200

        def json(self):
            return {
                "code": 0,
                "data": {
                    "access_token": "fresh-access-token",
                    "refresh_token": "fresh-refresh-token",
                },
                "msg": "",
            }

    def fake_post(url, *, data=None, json=None, headers, timeout):
        seen["url"] = url
        if url.endswith("/api/v4/session/oauth/token"):
            seen["data"] = data
            return FakeResponse()
        seen["refresh_json"] = json
        return FakeRefreshResponse()

    monkeypatch.setattr("nexus.cloudreve.oauth.requests.post", fake_post)
    client = make_client(settings=settings)

    response = client.get("/api/auth/cloudreve/callback?code=auth-code")

    assert response.status_code == 200
    assert response.json()["status"] == "authorized"
    assert seen["url"] == "http://cloudreve.local/api/v4/session/oauth/token"
    assert seen["data"]["grant_type"] == "authorization_code"
    assert seen["data"]["code"] == "auth-code"
    assert client.get("/api/auth/cloudreve/status").json()["authorized"] is True


def test_sync_endpoint_creates_job():
    client = make_client()

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
    client = make_client()

    response = client.post(
        "/api/ingestion/sync?process=true",
        json={"uri": "cloudreve://my/demo.md", "requested_by": "user-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "succeeded"
    assert body["processing"]["success"] is True
    assert seen["uri"] == "cloudreve://my/demo.md"
    assert seen["requested_by"] == "user-1"


def test_sync_endpoint_marks_failed_processing_job(monkeypatch):
    class FakePipeline:
        def __init__(self, **kwargs):
            pass

        def process_file(self, uri, requested_by):
            class Result:
                success = False
                summary = ""
                tags = []
                entities_count = 0
                relations_count = 0
                chunks_count = 0
                error = "download failed"
                processing_time_ms = 1

            return Result()

    monkeypatch.setattr("nexus.app_factory.SemanticPipeline", FakePipeline)
    client = make_client()

    response = client.post(
        "/api/ingestion/sync?process=true",
        json={"uri": "cloudreve://my/missing.md", "requested_by": "user-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "failed"
    assert body["job"]["error"] == "download failed"


def test_retry_job_endpoint_reprocesses_existing_job(monkeypatch):
    seen = {}

    class FakePipeline:
        def __init__(self, *, cloudreve_token, settings, repository, enable_neo4j, enable_milvus):
            seen["repository"] = repository

        def process_file(self, uri, requested_by):
            seen["uri"] = uri
            seen["requested_by"] = requested_by

            class Result:
                success = True
                summary = "processed again"
                tags = ["retry"]
                entities_count = 1
                relations_count = 0
                chunks_count = 1
                error = None
                processing_time_ms = 7

            return Result()

    monkeypatch.setattr("nexus.app_factory.SemanticPipeline", FakePipeline)
    client = make_client()
    job = client.post(
        "/api/ingestion/sync",
        json={"uri": "cloudreve://my/retry.md", "requested_by": "user-1"},
    ).json()

    response = client.post(f"/api/ingestion/jobs/{job['id']}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "succeeded"
    assert body["job"]["attempts"] == 1
    assert body["processing"]["success"] is True
    assert seen["uri"] == "cloudreve://my/retry.md"
    assert seen["requested_by"] == "user-1"


def test_retry_job_endpoint_preserves_failure_details(monkeypatch):
    class FakePipeline:
        def __init__(self, **kwargs):
            pass

        def process_file(self, uri, requested_by):
            class Result:
                success = False
                summary = ""
                tags = []
                entities_count = 0
                relations_count = 0
                chunks_count = 0
                error = "glm timeout"
                processing_time_ms = 9

            return Result()

    monkeypatch.setattr("nexus.app_factory.SemanticPipeline", FakePipeline)
    client = make_client()
    job = client.post(
        "/api/ingestion/sync",
        json={"uri": "cloudreve://my/bad.md", "requested_by": "user-1"},
    ).json()

    response = client.post(f"/api/ingestion/jobs/{job['id']}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "failed"
    assert body["job"]["attempts"] == 1
    assert body["job"]["error"] == "glm timeout"
    assert body["processing"]["error"] == "glm timeout"


def test_documents_and_jobs_endpoints_expose_processing_results():
    client = make_client()
    client.post(
        "/api/ingestion/demo-index",
        json={
            "uri": "cloudreve://my/a.md",
            "content": "Infrared sensor thermal calibration.",
            "requested_by": "user-1",
        },
    )
    client.post(
        "/api/ingestion/sync",
        json={"uri": "cloudreve://my/a.md", "requested_by": "user-1"},
    )

    documents = client.get("/api/documents")
    jobs = client.get("/api/ingestion/jobs")

    assert documents.status_code == 200
    assert documents.json()[0]["uri"] == "cloudreve://my/a.md"
    assert documents.json()[0]["chunk_count"] == 1
    assert jobs.status_code == 200
    assert jobs.json()[0]["uri"] == "cloudreve://my/a.md"


def test_graphrag_answer_does_not_include_inaccessible_content():
    client = make_client()
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
    client = make_client()
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
