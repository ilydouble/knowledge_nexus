from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
        job.stage = "queued"
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        job.finished_at = None
        job.error_code = None
        job.error = None
        return self.repository.update_job(job)

    def mark_stage(self, job_id: str, stage: str) -> IngestionJob:
        job = self._get_existing_job(job_id).model_copy()
        job.stage = stage
        return self.repository.update_job(job)

    def mark_succeeded(self, job_id: str) -> IngestionJob:
        job = self._get_existing_job(job_id).model_copy()
        job.status = "succeeded"
        job.stage = "persist"
        job.finished_at = datetime.now(UTC)
        job.error_code = None
        job.error = None
        return self.repository.update_job(job)

    def mark_skipped(self, job_id: str, reason: str) -> IngestionJob:
        """Mark a job as permanently skipped (unsupported / binary file type)."""
        job = self._get_existing_job(job_id).model_copy()
        job.status = "skipped"
        job.stage = "gate"
        job.finished_at = datetime.now(UTC)
        job.error_code = "skipped"
        job.error = reason
        return self.repository.update_job(job)

    def mark_failed(self, job_id: str, error: str, *, stage: str | None = None, error_code: str | None = None) -> IngestionJob:
        job = self._get_existing_job(job_id).model_copy()
        job.status = "failed"
        if stage:
            job.stage = stage
        job.finished_at = datetime.now(UTC)
        job.error_code = error_code
        job.error = error
        return self.repository.update_job(job)

    def list_files(self) -> list[dict[str, Any]]:
        jobs = self.repository.list_jobs()
        documents = {document.uri: document for document in self.repository.list_documents()}
        uris = set(documents)
        uris.update(job.uri for job in jobs)
        files = []
        for uri in uris:
            uri_jobs = [job for job in jobs if job.uri == uri]
            latest_job = uri_jobs[0] if uri_jobs else None
            document = documents.get(uri)
            if latest_job and latest_job.status == "failed":
                status = "failed"
            elif latest_job and latest_job.status == "skipped":
                status = "skipped"
            elif latest_job and latest_job.status == "running":
                status = "processing"
            elif document:
                status = "processed"
            elif latest_job:
                status = latest_job.status
            else:
                status = "pending"
            files.append(
                {
                    "uri": uri,
                    "filename": uri.rsplit("/", 1)[-1] or uri,
                    "source": latest_job.requested_by if latest_job else document.requested_by if document else "unknown",
                    "status": status,
                    "stage": latest_job.stage if latest_job and status != "processed" else "persist" if document else "queued",
                    "attempt_count": sum(job.attempts for job in uri_jobs) or len(uri_jobs),
                    "last_error": latest_job.error if latest_job else None,
                    "latest_job": latest_job,
                    "jobs": uri_jobs,
                    "semantic": (
                        {
                            "summary": document.summary,
                            "tags": document.tags,
                            "entities": document.entities,
                            "chunk_count": len(document.chunks),
                        }
                        if document
                        else None
                    ),
                    "updated_at": (
                        latest_job.finished_at
                        or latest_job.started_at
                        or latest_job.created_at
                        if latest_job
                        else None
                    ),
                }
            )
        return sorted(files, key=lambda item: item["updated_at"] or datetime.min.replace(tzinfo=UTC), reverse=True)

    def _get_existing_job(self, job_id: str) -> IngestionJob:
        job = self.repository.get_job(job_id)
        if job is None:
            raise KeyError(f"ingestion job not found: {job_id}")
        return job
