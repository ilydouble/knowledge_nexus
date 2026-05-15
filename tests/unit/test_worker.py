import asyncio

from nexus.models import IngestionJob
from nexus.worker import Worker, watch_cloudreve_events


def test_worker_passes_cloudreve_client_id(monkeypatch):
    seen = {}

    class FakeRepository:
        def list_jobs(self):
            return []

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

    monkeypatch.setattr("nexus.worker.build_repository", lambda settings: FakeRepository())
    monkeypatch.setattr("nexus.worker.FileEventHandler", FakeHandler)
    monkeypatch.setattr("nexus.worker.Settings.from_env", lambda: FakeSettings())
    monkeypatch.setattr("nexus.worker.CloudreveClient", FakeClient)

    asyncio.run(watch_cloudreve_events())

    assert seen["token"] is None
    assert seen["client_id"] == "knowledge-nexus-worker"
    # process_event now only queues; handle_events is still called to create the job
    assert seen["events"] == [{"type": "update", "uri": "cloudreve://my/demo.md"}]


def test_worker_queues_file_events_without_immediate_processing(monkeypatch):
    """SSE events should create pending jobs only; pipeline is NOT called inline.

    Actual processing is deferred to process_pending_loop so that LLM calls
    are batched and rate-controlled rather than fired on every upload event.
    """
    seen = {}

    class FakeRepository:
        def __init__(self):
            self.jobs = []

        def add_job(self, job):
            self.jobs.append(job)
            seen.setdefault("queued_uris", []).append(job.uri)
            return job

        def update_job(self, job):
            return job

        def get_job(self, job_id):
            for job in self.jobs:
                if job.id == job_id:
                    return job
            return None

        def list_jobs(self):
            return list(self.jobs)

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

    monkeypatch.setattr("nexus.worker.build_repository", lambda settings: FakeRepository())
    monkeypatch.setattr("nexus.worker.FileEventHandler", FakeHandler)
    monkeypatch.setattr("nexus.worker.Settings.from_env", lambda: FakeSettings())
    monkeypatch.setattr("nexus.worker.CloudreveClient", FakeClient)

    asyncio.run(watch_cloudreve_events())

    # Job was created via handle_events
    assert seen["jobs_for"] == [{"type": "update", "uri": "cloudreve://my/demo.md"}]
    # A pending job was queued for the URI
    assert "cloudreve://my/demo.md" in seen.get("queued_uris", [])
    # Pipeline was NOT called (no "processed_uri" recorded)
    assert "processed_uri" not in seen


def test_worker_uses_configured_repository_builder(monkeypatch):
    seen = {}

    class FakeRepository:
        def list_jobs(self):
            return []

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
    """run_forever should reconnect the SSE loop after it closes.

    The worker now runs three concurrent loops (SSE, scan, process_pending).
    We patch all three so the test only exercises the reconnect logic.
    """
    seen = {"runs": 0, "sleeps": 0}
    worker = Worker.__new__(Worker)

    async def fake_run():
        seen["runs"] += 1

    async def fake_sleep(delay):
        seen["sleeps"] += 1
        raise KeyboardInterrupt

    # Stub out the two new loops so they don't touch uninitialized state
    async def fake_scan_loop(interval=600.0):
        pass  # exits immediately

    async def fake_process_pending_loop(poll=30.0, batch=3):
        pass  # exits immediately

    monkeypatch.setattr(worker, "run", fake_run)
    monkeypatch.setattr(worker, "scan_loop", fake_scan_loop)
    monkeypatch.setattr(worker, "process_pending_loop", fake_process_pending_loop)
    monkeypatch.setattr("nexus.worker.asyncio.sleep", fake_sleep)

    try:
        asyncio.run(worker.run_forever(reconnect_delay_seconds=0.01))
    except KeyboardInterrupt:
        pass

    assert seen["runs"] == 1
    assert seen["sleeps"] == 1
