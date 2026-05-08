import asyncio

from nexus.worker import watch_cloudreve_events


def test_worker_passes_cloudreve_client_id(monkeypatch):
    seen = {}

    class FakeRepository:
        pass

    class FakeHandler:
        def __init__(self, repository):
            seen["repository"] = repository

        def handle_events(self, events):
            seen["events"] = events
            return []

    class FakeSettings:
        cloudreve_token = "token-123"
        cloudreve_client_id = "knowledge-nexus-worker"

    class FakeClient:
        def __init__(self, token=None):
            seen["token"] = token

        async def iter_file_events(self, uri="cloudreve://my", client_id=None):
            seen["uri"] = uri
            seen["client_id"] = client_id
            yield {"raw": '{"type":"update","uri":"cloudreve://my/demo.md"}'}

    monkeypatch.setattr("nexus.worker.InMemoryRepository", FakeRepository)
    monkeypatch.setattr("nexus.worker.FileEventHandler", FakeHandler)
    monkeypatch.setattr("nexus.worker.Settings.from_env", lambda: FakeSettings())
    monkeypatch.setattr("nexus.worker.CloudreveClient", FakeClient)

    asyncio.run(watch_cloudreve_events())

    assert seen["token"] == "token-123"
    assert seen["client_id"] == "knowledge-nexus-worker"
    assert seen["events"] == [{"type": "update", "uri": "cloudreve://my/demo.md"}]
