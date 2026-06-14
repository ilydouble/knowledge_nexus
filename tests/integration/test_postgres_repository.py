import os

import pytest

from core.models import KnowledgeLayer, KnowledgeLink
from core.repositories.postgres import PostgresRepository, initialize_postgres_schema
from core.settings import Settings


pytestmark = pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to run Postgres integration tests")


def test_postgres_repository_persists_links():
    settings = Settings.from_env()
    initialize_postgres_schema(settings.database_url)
    repository = PostgresRepository(settings.database_url)
    unique_uri = "cloudreve://integration/postgres-repository.md"
    target_uri = "cloudreve://integration/postgres-target.md"

    repository.delete_by_uri_for_tests(unique_uri)
    repository.delete_by_uri_for_tests(target_uri)

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
    assert any(lnk.id == link.id and lnk.relation == "RELATED_TO" for lnk in repository.list_links())

    repository.delete_by_uri_for_tests(unique_uri)
    repository.delete_by_uri_for_tests(target_uri)
