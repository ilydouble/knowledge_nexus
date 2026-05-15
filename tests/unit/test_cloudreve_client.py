import asyncio

import httpx
import pytest

from nexus.cloudreve.client import CloudreveClient, CloudreveError


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


def test_iter_file_events_surfaces_actionable_hint_on_bad_gateway(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 502

        def iter_lines(self, decode_unicode=True):
            return iter(())

    def fake_get(url, *, params, headers, stream, timeout):
        seen["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("nexus.cloudreve.client.requests.get", fake_get)

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


def test_get_file_content_sync_refreshes_expired_access_token_and_retries(monkeypatch):
    seen = {"get_headers": [], "post_payloads": []}

    class FakeContentResponse:
        def __init__(self, status_code, content=b""):
            self.status_code = status_code
            self.content = content

    class FakeRefreshResponse:
        status_code = 200

        def json(self):
            return {
                "code": 0,
                "data": {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "access_expires": "2026-05-15T12:00:00+08:00",
                    "refresh_expires": "2026-06-15T12:00:00+08:00",
                },
                "msg": "",
            }

    responses = [
        FakeContentResponse(401),
        FakeContentResponse(200, b"downloaded"),
    ]

    def fake_get(url, *, params, headers, timeout, **kwargs):
        seen["get_headers"].append(headers)
        return responses.pop(0)

    def fake_post(url, *, json, headers, timeout):
        seen["post_payloads"].append(json)
        return FakeRefreshResponse()

    monkeypatch.setattr("nexus.cloudreve.client.requests.get", fake_get)
    monkeypatch.setattr("nexus.cloudreve.client.requests.post", fake_post)

    client = CloudreveClient(base_url="http://localhost:5212", token="old-access", refresh_token="old-refresh")

    content = client.get_file_content_sync("cloudreve://my/demo.md")

    assert content == b"downloaded"
    assert seen["post_payloads"] == [{"refresh_token": "old-refresh"}]
    assert seen["get_headers"][0]["Authorization"] == "Bearer old-access"
    assert seen["get_headers"][1]["Authorization"] == "Bearer new-access"
    assert client.token == "new-access"
    assert client.refresh_token == "new-refresh"


def test_iter_file_events_refreshes_expired_access_token_before_streaming(monkeypatch):
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

    monkeypatch.setattr("nexus.cloudreve.client.requests.get", fake_get)
    monkeypatch.setattr("nexus.cloudreve.client.requests.post", lambda *args, **kwargs: FakeRefreshResponse())

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
