from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from nexus.settings import Settings


class CloudreveOAuthError(RuntimeError):
    pass


class CloudreveOAuthTokenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.load()
        existing.update(payload)
        self.path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def status(self) -> dict[str, Any]:
        payload = self.load()
        if not payload.get("access_token") and not payload.get("refresh_token"):
            return {"authorized": False}
        return {
            "authorized": True,
            "has_access_token": bool(payload.get("access_token")),
            "has_refresh_token": bool(payload.get("refresh_token")),
        }


def build_authorization_url(settings: Settings, *, state: str | None = None) -> str:
    if not settings.cloudreve_oauth_client_id:
        raise CloudreveOAuthError("CLOUDREVE_OAUTH_CLIENT_ID is required")
    params = {
        "response_type": "code",
        "client_id": settings.cloudreve_oauth_client_id,
        "redirect_uri": settings.cloudreve_oauth_redirect_uri,
        "scope": settings.cloudreve_oauth_scope,
    }
    if state:
        params["state"] = state
    return f"{settings.cloudreve_base_url.rstrip('/')}/session/authorize?{urlencode(params)}"


def unwrap_token_response(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if payload.get("code") == 0 else payload
    if not isinstance(data, dict):
        raise CloudreveOAuthError("Cloudreve OAuth token response did not include token data")
    if not data.get("access_token") and not data.get("refresh_token"):
        raise CloudreveOAuthError("Cloudreve OAuth token response did not include access_token or refresh_token")
    return data


def exchange_authorization_code(settings: Settings, code: str) -> dict[str, Any]:
    if not settings.cloudreve_oauth_client_id or not settings.cloudreve_oauth_client_secret:
        raise CloudreveOAuthError("CLOUDREVE_OAUTH_CLIENT_ID and CLOUDREVE_OAUTH_CLIENT_SECRET are required")
    response = requests.post(
        f"{settings.cloudreve_base_url.rstrip('/')}/api/v4/session/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.cloudreve_oauth_client_id,
            "client_secret": settings.cloudreve_oauth_client_secret,
            "code": code,
            "redirect_uri": settings.cloudreve_oauth_redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    return unwrap_token_response(response.json())


def refresh_oauth_tokens(settings: Settings, refresh_token: str) -> dict[str, Any]:
    response = requests.post(
        f"{settings.cloudreve_base_url.rstrip('/')}/api/v4/session/token/refresh",
        json={"refresh_token": refresh_token},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=20,
    )
    if response.status_code != 200:
        raise CloudreveOAuthError("refresh_failed")
    return unwrap_token_response(response.json())
