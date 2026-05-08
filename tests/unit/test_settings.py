from nexus.settings import Settings


def test_settings_loads_database_url_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://admin:admin123@localhost:5433/smart_building")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql://admin:admin123@localhost:5433/smart_building"


def test_settings_missing_optional_ai_key_does_not_crash(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.openai_api_key is None


def test_settings_default_vector_backend_is_milvus(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)

    settings = Settings.from_env()

    assert settings.vector_backend == "milvus"


def test_settings_default_cloudreve_client_id(monkeypatch):
    monkeypatch.delenv("CLOUDREVE_CLIENT_ID", raising=False)

    settings = Settings.from_env()

    assert settings.cloudreve_client_id == "knowledge-nexus-worker"
