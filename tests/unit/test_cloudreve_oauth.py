from nexus.cloudreve.oauth import CloudreveOAuthTokenStore


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
