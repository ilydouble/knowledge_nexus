from apps.api.factory import build_repository, create_application
from core.repositories.memory import InMemoryRepository
from core.repositories.postgres import PostgresRepository
from core.settings import Settings


def test_build_repository_defaults_to_memory_backend(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEXUS_STORAGE_BACKEND", raising=False)

    repository = build_repository(Settings.from_env())

    assert isinstance(repository, InMemoryRepository)


def test_build_repository_uses_postgres_backend_when_configured():
    settings = Settings.from_env().__class__(
        nexus_storage_backend="postgres",
        database_url="postgresql://admin:admin123@localhost:5433/smart_building",
    )

    repository = build_repository(settings)

    assert isinstance(repository, PostgresRepository)
    assert repository.database_url == "postgresql://admin:admin123@localhost:5433/smart_building"


def test_create_application_keeps_explicit_repository_seam():
    repository = InMemoryRepository()

    app = create_application(repository=repository)

    assert app.state.repository is repository
