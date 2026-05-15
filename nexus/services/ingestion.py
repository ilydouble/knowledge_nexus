from __future__ import annotations

from nexus.models import IngestionJob, SyncRequest
from nexus.repositories.base import NexusRepository


class IngestionService:
    def __init__(self, repository: NexusRepository) -> None:
        self.repository = repository

    def sync(self, request: SyncRequest) -> IngestionJob:
        job = IngestionJob(uri=request.uri, requested_by=request.requested_by)
        return self.repository.add_job(job)

    def list_jobs(self) -> list[IngestionJob]:
        return self.repository.list_jobs()

    def mark_running(self, job_id: str) -> IngestionJob:
        job = self._get_existing_job(job_id).model_copy()
        job.status = "running"
        job.attempts += 1
        job.error = None
        return self.repository.update_job(job)

    def mark_succeeded(self, job_id: str) -> IngestionJob:
        job = self._get_existing_job(job_id).model_copy()
        job.status = "succeeded"
        job.error = None
        return self.repository.update_job(job)

    def mark_failed(self, job_id: str, error: str) -> IngestionJob:
        job = self._get_existing_job(job_id).model_copy()
        job.status = "failed"
        job.error = error
        return self.repository.update_job(job)

    def _get_existing_job(self, job_id: str) -> IngestionJob:
        job = self.repository.get_job(job_id)
        if job is None:
            raise KeyError(f"ingestion job not found: {job_id}")
        return job
