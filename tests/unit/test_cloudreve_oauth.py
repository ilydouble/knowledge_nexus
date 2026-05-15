from nexus.cloudreve.oauth import CloudreveOAuthConfigStore, CloudreveOAuthTokenStore, resolve_oauth_settings
from nexus.settings import Settings


def test_oauth_token_store_saves_and_loads_tokens(tmp_path):
    path = tmp_path / "runtime" / "cloudreve_tokens.json"
    store = CloudreveOAuthTokenStore(path)

    store.save(
        {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "refresh_token_expires_in": 7776000,
        }
    )

    loaded = store.load()
    assert loaded["access_token"] == "access-token"
    assert loaded["refresh_token"] == "refresh-token"
    assert store.status()["authorized"] is True


def test_oauth_token_store_reports_missing_authorization(tmp_path):
    store = CloudreveOAuthTokenStore(tmp_path / "missing.json")

    assert store.load() == {}
    assert store.status() == {"authorized": False}


def test_oauth_config_store_saves_non_token_oauth_settings(tmp_path):
    store = CloudreveOAuthConfigStore(tmp_path / "oauth_config.json")

    store.save(
        {
            "cloudreve_base_url": "http://localhost:5212",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "http://localhost:8000/api/auth/cloudreve/callback",
            "scope": "offline_access",
        }
    )

    assert store.load()["client_id"] == "client-id"
    assert store.load()["scope"] == "openid offline_access"
    assert store.status()["configured"] is True
    assert store.status()["client_secret_set"] is True


def test_resolve_oauth_settings_prefers_runtime_config(tmp_path):
    path = tmp_path / "oauth_config.json"
    CloudreveOAuthConfigStore(path).save(
        {
            "cloudreve_base_url": "http://cloudreve.local",
            "client_id": "runtime-client",
            "client_secret": "runtime-secret",
            "redirect_uri": "http://localhost:8000/api/auth/cloudreve/callback",
            "scope": "offline_access",
        }
    )
    settings = Settings(
        cloudreve_oauth_config_path=str(path),
        cloudreve_oauth_client_id=None,
        cloudreve_oauth_client_secret=None,
    )

    resolved = resolve_oauth_settings(settings)

    assert resolved.cloudreve_base_url == "http://cloudreve.local"
    assert resolved.cloudreve_oauth_client_id == "runtime-client"
    assert resolved.cloudreve_oauth_client_secret == "runtime-secret"
    assert resolved.cloudreve_oauth_scope == "openid offline_access"
