from nexus.models import KnowledgeLayer, LinkCreate, SyncRequest
from nexus.repository import InMemoryRepository
from nexus.services.ingestion import IngestionService
from nexus.services.links import LinkService


def test_manual_sync_creates_pending_ingestion_job():
    repository = InMemoryRepository()
    service = IngestionService(repository)

    job = service.sync(SyncRequest(uri="cloudreve://my/projects/report.md", requested_by="user-1"))

    assert job.status == "pending"
    assert job.uri == "cloudreve://my/projects/report.md"
    assert repository.get_job(job.id) == job


def test_ingestion_service_updates_job_status_and_lists_recent_jobs():
    repository = InMemoryRepository()
    service = IngestionService(repository)
    job = service.sync(SyncRequest(uri="cloudreve://my/projects/report.md", requested_by="user-1"))

    running = service.mark_running(job.id)
    finished = service.mark_succeeded(job.id)

    assert running.status == "running"
    assert finished.status == "succeeded"
    assert finished.error is None
    assert repository.list_jobs()[0].id == job.id


def test_ingestion_service_records_failed_job_error():
    repository = InMemoryRepository()
    service = IngestionService(repository)
    job = service.sync(SyncRequest(uri="cloudreve://my/projects/report.md", requested_by="user-1"))

    failed = service.mark_failed(job.id, "download failed")

    assert failed.status == "failed"
    assert failed.error == "download failed"


def test_personal_link_defaults_to_l3_private_visibility():
    repository = InMemoryRepository()
    service = LinkService(repository)

    link = service.create_link(
        LinkCreate(
            source_uri="cloudreve://my/a.md",
            target_uri="cloudreve://my/b.md",
            relation="REFERENCES",
            created_by="user-1",
        )
    )

    assert link.layer == KnowledgeLayer.L3
    assert link.visibility == "private"
    assert link.owner_scope == "user:user-1"
