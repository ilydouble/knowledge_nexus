import asyncio

from nexus.models import IngestionJob
from nexus.worker import Worker, watch_cloudreve_events


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

    class FakePipeline:
        def __init__(self, **kwargs):
            pass

        def process_file(self, uri, requested_by):
            class Result:
                success = True
                entities_count = 0
                relations_count = 0
                chunks_count = 0
                processing_time_ms = 0
                error = None

            return Result()

    monkeypatch.setattr("nexus.worker.build_repository", lambda settings: FakeRepository())
    monkeypatch.setattr("nexus.worker.FileEventHandler", FakeHandler)
    monkeypatch.setattr("nexus.worker.Settings.from_env", lambda: FakeSettings())
    monkeypatch.setattr("nexus.worker.CloudreveClient", FakeClient)
    monkeypatch.setattr("nexus.worker.SemanticPipeline", FakePipeline)

    asyncio.run(watch_cloudreve_events())

    assert seen["token"] == "token-123"
    assert seen["client_id"] == "knowledge-nexus-worker"
    assert seen["events"] == [{"type": "update", "uri": "cloudreve://my/demo.md"}]


def test_worker_processes_file_events_with_pipeline(monkeypatch):
    seen = {}

    class FakeRepository:
        def __init__(self):
            self.jobs = []

        def add_job(self, job):
            self.jobs.append(job)
            return job

        def update_job(self, job):
            seen.setdefault("updated_statuses", []).append(job.status)
            return job

        def get_job(self, job_id):
            for job in self.jobs:
                if job.id == job_id:
                    return job
            return None

    class FakeHandler:
        def __init__(self, repository):
            self.repository = repository

        def handle_events(self, events):
            seen["jobs_for"] = events
            job = IngestionJob(uri=events[0]["uri"], requested_by="worker")
            self.repository.add_job(job)
            return [job]

    class FakeSettings:
        cloudreve_token = "token-123"
        cloudreve_client_id = "client-id"
        cloudreve_base_url = "http://localhost:5212"
        neo4j_uri = ""
        milvus_host = ""

    class FakeClient:
        def __init__(self, token=None):
            pass

        async def iter_file_events(self, uri="cloudreve://my", client_id=None):
            yield {"type": "connected"}
            yield {"type": "event", "raw": '{"type":"update","uri":"cloudreve://my/demo.md"}'}

    class FakePipeline:
        def __init__(self, *, cloudreve_token, settings, repository, enable_neo4j, enable_milvus):
            seen["pipeline_token"] = cloudreve_token
            seen["pipeline_repository"] = repository

        def process_file(self, uri, requested_by):
            seen["processed_uri"] = uri
            seen["processed_by"] = requested_by

            class Result:
                success = True
                entities_count = 1
                relations_count = 0
                chunks_count = 1
                processing_time_ms = 5
                error = None

            return Result()

    monkeypatch.setattr("nexus.worker.build_repository", lambda settings: FakeRepository())
    monkeypatch.setattr("nexus.worker.FileEventHandler", FakeHandler)
    monkeypatch.setattr("nexus.worker.Settings.from_env", lambda: FakeSettings())
    monkeypatch.setattr("nexus.worker.CloudreveClient", FakeClient)
    monkeypatch.setattr("nexus.worker.SemanticPipeline", FakePipeline)

    asyncio.run(watch_cloudreve_events())

    assert seen["jobs_for"] == [{"type": "update", "uri": "cloudreve://my/demo.md"}]
    assert seen["processed_uri"] == "cloudreve://my/demo.md"
    assert seen["processed_by"] == "worker"
    assert seen["updated_statuses"] == ["running", "succeeded"]


def test_worker_uses_configured_repository_builder(monkeypatch):
    seen = {}

    class FakeRepository:
        pass

    class FakeSettings:
        cloudreve_token = "token-123"
        cloudreve_client_id = "client-id"
        cloudreve_base_url = "http://localhost:5212"

    class FakeClient:
        def __init__(self, token=None):
            pass

        async def iter_file_events(self, uri="cloudreve://my", client_id=None):
            if False:
                yield {}

    class FakeHandler:
        def __init__(self, repository):
            seen["handler_repository"] = repository

    repository = FakeRepository()
    monkeypatch.setattr("nexus.worker.Settings.from_env", lambda: FakeSettings())
    monkeypatch.setattr("nexus.worker.CloudreveClient", FakeClient)
    monkeypatch.setattr("nexus.worker.FileEventHandler", FakeHandler)
    monkeypatch.setattr("nexus.worker.build_repository", lambda settings: repository)

    asyncio.run(watch_cloudreve_events())

    assert seen["handler_repository"] is repository


def test_worker_run_forever_reconnects_after_stream_closes(monkeypatch):
    seen = {"runs": 0, "sleeps": 0}
    worker = Worker.__new__(Worker)

    async def fake_run():
        seen["runs"] += 1

    async def fake_sleep(delay):
        seen["sleeps"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "run", fake_run)
    monkeypatch.setattr("nexus.worker.asyncio.sleep", fake_sleep)

    try:
        asyncio.run(worker.run_forever(reconnect_delay_seconds=0.01))
    except KeyboardInterrupt:
        pass

    assert seen["runs"] == 1
    assert seen["sleeps"] == 1
