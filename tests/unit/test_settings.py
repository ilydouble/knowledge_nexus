import uuid
from pathlib import Path

from core.settings import Settings


def test_settings_loads_database_url_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://admin:admin123@localhost:5433/smart_building")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql://admin:admin123@localhost:5433/smart_building"


def test_settings_missing_optional_ai_key_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("BIGMODEL_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.openai_api_key is None
    assert settings.zhipu_api_key is None


def test_settings_defaults_to_glm47_for_llm_extraction(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = Settings.from_env()

    assert settings.llm_provider == "zhipu"
    assert settings.llm_model == "glm-4.7"


def test_settings_loads_zhipu_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")

    settings = Settings.from_env()

    assert settings.zhipu_api_key == "zhipu-key"


def test_settings_class_default_vector_backend_is_milvus():
    # Tests the dataclass class-level default (not env-overridden).
    # The deployment .env may set VECTOR_BACKEND=none to disable Milvus,
    # but the code infrastructure defaults to "milvus" so it's opt-in.
    settings = Settings()  # no env loading
    assert settings.vector_backend == "milvus"


def test_settings_default_cloudreve_client_id(monkeypatch):
    monkeypatch.delenv("CLOUDREVE_CLIENT_ID", raising=False)

    settings = Settings.from_env()

    assert str(uuid.UUID(settings.cloudreve_client_id)) == settings.cloudreve_client_id


def test_settings_loads_values_from_dotenv_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLOUDREVE_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDREVE_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDREVE_CLIENT_ID", raising=False)
    Path(tmp_path / ".env").write_text(
        "CLOUDREVE_BASE_URL=http://localhost:5212\n"
        "CLOUDREVE_TOKEN=test-token\n"
        "CLOUDREVE_CLIENT_ID=test-client\n",
        encoding="utf-8",
    )

    settings = Settings.from_env()

    assert settings.cloudreve_base_url == "http://localhost:5212"
    assert settings.cloudreve_token == "test-token"
    assert settings.cloudreve_client_id == "test-client"


def test_settings_loads_cloudreve_refresh_token(monkeypatch):
    monkeypatch.setenv("CLOUDREVE_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("CLOUDREVE_REFRESH_TOKEN", "refresh-token")

    settings = Settings.from_env()

    assert settings.cloudreve_access_token == "access-token"
    assert settings.cloudreve_refresh_token == "refresh-token"
    assert settings.cloudreve_token == "access-token"


def test_settings_loads_cloudreve_oauth_settings(monkeypatch):
    monkeypatch.setenv("CLOUDREVE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("CLOUDREVE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("CLOUDREVE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/auth/cloudreve/callback")
    monkeypatch.setenv("CLOUDREVE_TOKEN_STORE_PATH", "data/runtime/tokens.json")

    settings = Settings.from_env()

    assert settings.cloudreve_oauth_client_id == "client-id"
    assert settings.cloudreve_oauth_client_secret == "client-secret"
    assert settings.cloudreve_oauth_redirect_uri == "http://localhost:8000/api/auth/cloudreve/callback"
    assert settings.cloudreve_oauth_scope == "openid profile offline_access Files.Read"
    assert settings.cloudreve_token_store_path == "data/runtime/tokens.json"


def test_settings_loads_cloudreve_oauth_config_path(monkeypatch):
    monkeypatch.setenv("CLOUDREVE_OAUTH_CONFIG_PATH", "data/runtime/oauth_config.json")

    settings = Settings.from_env()

    assert settings.cloudreve_oauth_config_path == "data/runtime/oauth_config.json"
