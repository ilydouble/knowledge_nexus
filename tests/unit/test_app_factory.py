from apps.api.factory import build_repository, create_application
from core.repositories.memory import InMemoryRepository
from core.repositories.postgres import PostgresRepository
from core.settings import Settings
from core.storage.artifact_store import LocalArtifactStore, build_artifact_store


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


# ── LocalArtifactStore tests ──────────────────────────────────────────────────

def test_local_artifact_store_write_returns_local_uri(tmp_path):
    store = LocalArtifactStore(base_dir=str(tmp_path))
    uri = store.write("abc123def456", "report.pdf", "Hello world text.")
    assert uri.startswith("local://")
    assert uri.endswith(".txt")


def test_local_artifact_store_roundtrip(tmp_path):
    """Write then read should return the original text."""
    store = LocalArtifactStore(base_dir=str(tmp_path))
    text = "Full parsed document content."
    uri = store.write("deadbeef1234", "doc.pdf", text)
    assert store.read(uri) == text


def test_local_artifact_store_delete_removes_file(tmp_path):
    store = LocalArtifactStore(base_dir=str(tmp_path))
    uri = store.write("cafebabe5678", "notes.txt", "Some notes.")
    # File must exist before delete
    path = uri[len("local://"):]
    import os
    assert os.path.exists(path)
    store.delete(uri)
    assert not os.path.exists(path)


def test_local_artifact_store_delete_is_idempotent(tmp_path):
    """Deleting a non-existent file should not raise."""
    store = LocalArtifactStore(base_dir=str(tmp_path))
    store.delete("local:///nonexistent/path/file.txt")  # no error


def test_local_artifact_store_delete_ignores_non_local_uri(tmp_path):
    """delete() on an s3:// URI is a no-op."""
    store = LocalArtifactStore(base_dir=str(tmp_path))
    store.delete("s3://some-bucket/key.txt")  # no error


def test_build_artifact_store_falls_back_to_local_when_minio_unreachable(tmp_path):
    """When MinIO cannot be reached, build_artifact_store returns a LocalArtifactStore."""
    store = build_artifact_store(
        endpoint="http://127.0.0.1:19999",  # nothing listening here
        access_key="x",
        secret_key="x",
        bucket="test",
        local_dir=str(tmp_path),
    )
    assert isinstance(store, LocalArtifactStore)
    # The fallback store must be usable immediately.
    uri = store.write("aabb1122ccdd", "test.txt", "fallback content")
    assert store.read(uri) == "fallback content"


def test_settings_artifact_local_dir_defaults_to_data_artifacts():
    settings = Settings()
    assert settings.artifact_local_dir == "data/artifacts"


def test_settings_artifact_local_dir_readable_from_env(monkeypatch):
    monkeypatch.setenv("ARTIFACT_LOCAL_DIR", "/tmp/my_artifacts")
    settings = Settings.from_env()
    assert settings.artifact_local_dir == "/tmp/my_artifacts"
