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
