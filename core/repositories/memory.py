from __future__ import annotations

from core.models import IngestionJob, KnowledgeLink


class InMemoryRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, IngestionJob] = {}
        self.links: dict[str, KnowledgeLink] = {}

    def add_job(self, job: IngestionJob) -> IngestionJob:
        self.jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> IngestionJob | None:
        return self.jobs.get(job_id)

    def update_job(self, job: IngestionJob) -> IngestionJob:
        self.jobs[job.id] = job
        return job

    def list_jobs(self) -> list[IngestionJob]:
        return sorted(self.jobs.values(), key=lambda job: job.created_at, reverse=True)

    def add_link(self, link: KnowledgeLink) -> KnowledgeLink:
        self.links[link.id] = link
        return link

    def list_links(self) -> list[KnowledgeLink]:
        return list(self.links.values())

    def delete_document(self, uri: str) -> None:
        """No-op: semantic documents no longer stored in this repository."""
