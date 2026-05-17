import os

import pytest

from nexus.models import IngestionJob, KnowledgeLayer, KnowledgeLink, SemanticDocument, TextChunk
from nexus.repositories.postgres import PostgresRepository, initialize_postgres_schema
from nexus.settings import Settings


pytestmark = pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to run Postgres integration tests")


def test_postgres_repository_persists_jobs_documents_chunks_and_links():
    settings = Settings.from_env()
    initialize_postgres_schema(settings.database_url)
    repository = PostgresRepository(settings.database_url)
    unique_uri = "cloudreve://integration/postgres-repository.md"
    target_uri = "cloudreve://integration/postgres-target.md"

    repository.delete_by_uri_for_tests(unique_uri)
    repository.delete_by_uri_for_tests(target_uri)

    job = repository.add_job(IngestionJob(uri=unique_uri, requested_by="integration-user"))
    assert repository.get_job(job.id) == job

    document = repository.add_document(
        SemanticDocument(
            uri=unique_uri,
            summary="Persisted infrared sensor notes",
            tags=["infrared", "sensor"],
            entities=["Infrared"],
            chunks=[
                TextChunk(id=f"{unique_uri}#chunk-1", text="Persisted infrared sensor notes", index=1),
                TextChunk(id=f"{unique_uri}#chunk-2", text="Thermal calibration context", index=2),
            ],
            requested_by="integration-user",
        )
    )
    assert repository.get_document(unique_uri) == document

    link = repository.add_link(
        KnowledgeLink(
            source_uri=unique_uri,
            target_uri=target_uri,
            relation="RELATED_TO",
            layer=KnowledgeLayer.L3,
            owner_scope="user:integration-user",
            source_file_uri=unique_uri,
            visibility="private",
            created_by="integration-user",
        )
    )
    assert repository.list_links() == [link]

    nodes, edges = repository.graph()
    assert any(node.uri == unique_uri and node.summary == document.summary for node in nodes)
    assert any(edge.id == link.id and edge.relation == "RELATED_TO" for edge in edges)

    repository.delete_by_uri_for_tests(unique_uri)
    repository.delete_by_uri_for_tests(target_uri)

