import asyncio

import httpx
import pytest

from core.cloudreve.client import CloudreveClient, CloudreveError


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_cloudreve_client_unwraps_success_response():
    data = CloudreveClient.unwrap_response(FakeResponse({"code": 0, "data": {"id": 1}, "msg": ""}))

    assert data == {"id": 1}


def test_cloudreve_client_raises_on_cloudreve_error_code():
    with pytest.raises(CloudreveError) as exc:
        CloudreveClient.unwrap_response(FakeResponse({"code": 403, "msg": "No Permission to Access"}))

    assert exc.value.code == 403
    assert "No Permission" in str(exc.value)


def test_cloudreve_client_uses_settings_default_base_url(monkeypatch):
    monkeypatch.setenv("CLOUDREVE_BASE_URL", "http://localhost:5212")

    client = CloudreveClient()

    assert client.base_url == "http://localhost:5212"


def test_cloudreve_client_prefers_oauth_token_store_over_legacy_env_token(monkeypatch, tmp_path):
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        '{"access_token":"store-access","refresh_token":"store-refresh"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLOUDREVE_TOKEN_STORE_PATH", str(token_path))
    monkeypatch.setenv("CLOUDREVE_ACCESS_TOKEN", "expired-env-access")
    monkeypatch.delenv("CLOUDREVE_REFRESH_TOKEN", raising=False)

    client = CloudreveClient()

    assert client.token == "store-access"
    assert client.refresh_token == "store-refresh"


def test_iter_file_events_surfaces_actionable_hint_on_bad_gateway(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 502

        def iter_lines(self, decode_unicode=True):
            return iter(())

    def fake_get(url, *, params, headers, stream, timeout):
        seen["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("core.cloudreve.client.requests.get", fake_get)

    client = CloudreveClient(base_url="http://localhost:5212", token="U_qfDZdYiMTYn15zm9NHSON9CHf6LM49ark_KQgptA0")

    async def consume():
        async for _event in client.iter_file_events():
            pytest.fail("expected iter_file_events to raise before yielding events")

    with pytest.raises(CloudreveError) as exc:
        asyncio.run(consume())

    assert seen["headers"]["Accept"] == "text/event-stream"
    assert exc.value.code == 502
    assert "CLOUDREVE_TOKEN" in str(exc.value)
    assert "/session/authn" in str(exc.value)


def test_get_file_content_sync_refreshes_expired_access_token_and_retries(monkeypatch, tmp_path):
    """Verify the two-step Cloudreve Pro v4 download flow with token refresh.

    Flow:
      1. POST /api/v4/file/url  → 401 (expired)
      2. POST /api/v4/session/token/refresh → new tokens
      3. POST /api/v4/file/url  → 200, signed URL
      4. GET <signed-url>       → raw bytes
    """
    seen = {"post_calls": [], "get_calls": []}

    SIGNED_URL = "http://localhost:5212/api/v4/file/content/abc/0/demo.md?sign=xyz"

    class FakeUrlResponse401:
        status_code = 401
        def json(self): return {"code": 401, "msg": "Login required"}

    class FakeUrlResponseOK:
        status_code = 200
        def json(self): return {"code": 0, "data": {"urls": [{"url": SIGNED_URL}]}, "msg": ""}

    class FakeRefreshResponse:
        status_code = 200
        def json(self):
            return {
                "code": 0,
                "data": {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                },
                "msg": "",
            }

    class FakeDownloadResponse:
        status_code = 200
        content = b"pdf-bytes"

        def iter_content(self, chunk_size=None):
            yield self.content

    url_responses = [FakeUrlResponse401(), FakeUrlResponseOK()]

    def fake_post(url, *, json=None, data=None, headers, timeout, **kwargs):
        seen["post_calls"].append({"url": url, "json": json})
        if "token/refresh" in url:
            return FakeRefreshResponse()
        return url_responses.pop(0)

    def fake_get(url, *, timeout, **kwargs):
        seen["get_calls"].append(url)
        return FakeDownloadResponse()

    # Isolate the token store so the refresh never touches the real credentials file.
    monkeypatch.setenv("CLOUDREVE_TOKEN_STORE_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setattr("core.cloudreve.client.requests.post", fake_post)
    monkeypatch.setattr("core.cloudreve.client.requests.get", fake_get)
    # The token refresh POST is issued from core.cloudreve.oauth, not the client.
    monkeypatch.setattr("core.cloudreve.oauth.requests.post", fake_post)

    client = CloudreveClient(base_url="http://localhost:5212", token="old-access", refresh_token="old-refresh")
    content = client.get_file_content_sync("cloudreve://my/demo.md")

    assert content == b"pdf-bytes"
    # Signed URL was fetched
    assert seen["get_calls"] == [SIGNED_URL]
    # POST /api/v4/file/url was called twice (before and after refresh)
    url_posts = [c for c in seen["post_calls"] if "file/url" in c["url"]]
    assert len(url_posts) == 2
    assert url_posts[0]["json"] == {"uris": ["cloudreve://my/demo.md"]}
    # Token refresh was triggered once
    refresh_posts = [c for c in seen["post_calls"] if "token/refresh" in c["url"]]
    assert len(refresh_posts) == 1
    assert client.token == "new-access"
    assert client.refresh_token == "new-refresh"


def test_iter_file_events_refreshes_expired_access_token_before_streaming(monkeypatch, tmp_path):
    seen = {"get_headers": []}

    class FakeStreamResponse:
        def __init__(self, status_code, lines=()):
            self.status_code = status_code
            self._lines = lines

        def iter_lines(self, decode_unicode=True):
            return iter(self._lines)

    class FakeRefreshResponse:
        status_code = 200

        def json(self):
            return {
                "code": 0,
                "data": {
                    "access_token": "fresh-access",
                    "refresh_token": "fresh-refresh",
                },
                "msg": "",
            }

    responses = [
        FakeStreamResponse(401),
        FakeStreamResponse(200, ["event: event", 'data: {"type":"update","uri":"cloudreve://my/demo.md"}']),
    ]

    def fake_get(url, *, params, headers, stream, timeout):
        seen["get_headers"].append(headers)
        return responses.pop(0)

    def fake_refresh_post(*args, **kwargs):
        return FakeRefreshResponse()

    # Isolate the token store so the refresh never touches the real credentials file.
    monkeypatch.setenv("CLOUDREVE_TOKEN_STORE_PATH", str(tmp_path / "tokens.json"))
    monkeypatch.setattr("core.cloudreve.client.requests.get", fake_get)
    # The token refresh POST is issued from core.cloudreve.oauth, not the client.
    monkeypatch.setattr("core.cloudreve.oauth.requests.post", fake_refresh_post)

    client = CloudreveClient(base_url="http://localhost:5212", token="expired-access", refresh_token="refresh-token")

    async def consume():
        events = []
        async for event in client.iter_file_events(client_id="client-id"):
            events.append(event)
        return events

    events = asyncio.run(consume())

    assert events[0] == {"type": "connected"}
    assert events[1]["raw"] == '{"type":"update","uri":"cloudreve://my/demo.md"}'
    assert seen["get_headers"][0]["Authorization"] == "Bearer expired-access"
    assert seen["get_headers"][1]["Authorization"] == "Bearer fresh-access"
