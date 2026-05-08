from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from nexus.settings import Settings


class CloudreveError(RuntimeError):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Cloudreve API error {code}: {message}")


@dataclass
class CloudreveClient:
    base_url: str | None = None
    token: str | None = None
    timeout: float = 20.0

    def __post_init__(self) -> None:
        if self.base_url is None:
            self.base_url = Settings.from_env().cloudreve_base_url

    @staticmethod
    def unwrap_response(response: Any) -> Any:
        payload = response.json()
        code = payload.get("code")
        if code != 0:
            raise CloudreveError(code=code, message=payload.get("msg") or "Unknown Cloudreve error")
        return payload.get("data")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _raise_http_error(self, exc: httpx.HTTPStatusError, *, endpoint: str) -> None:
        status_code = exc.response.status_code
        message = f"Cloudreve HTTP {status_code} while calling {endpoint}."
        if endpoint == "/api/v4/file/events" and status_code == 502:
            message = (
                f"{message} The events stream usually needs a valid Cloudreve API bearer token. "
                "It also expects X-Cr-Client-Id to be a UUID. "
                "If CLOUDREVE_TOKEN came from /api/v4/session/authn, that value is only a WebAuthn "
                "challenge and cannot authenticate the worker."
            )
        raise CloudreveError(code=status_code, message=message) from exc

    async def list_files(self, uri: str) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, headers=self._headers()) as client:
            response = await client.get("/api/v4/file/list", params={"uri": uri})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._raise_http_error(exc, endpoint="/api/v4/file/list")
        return self.unwrap_response(response)

    async def get_metadata(self, uri: str) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, headers=self._headers()) as client:
            response = await client.get("/api/v4/file/metadata", params={"uri": uri})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._raise_http_error(exc, endpoint="/api/v4/file/metadata")
        return self.unwrap_response(response)

    async def can_access(self, uri: str) -> bool:
        try:
            await self.get_metadata(uri)
            return True
        except CloudreveError as exc:
            if exc.code in {403, 404, 40044}:
                return False
            raise

    async def iter_file_events(self, uri: str = "cloudreve://my", client_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        if client_id:
            headers["X-Cr-Client-Id"] = client_id
        async with httpx.AsyncClient(base_url=self.base_url, timeout=None, headers=headers) as client:
            async with client.stream("GET", "/api/v4/file/events", params={"uri": uri}) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    self._raise_http_error(exc, endpoint="/api/v4/file/events")
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield {"raw": line.removeprefix("data: ")}
