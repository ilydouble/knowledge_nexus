from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import requests

from nexus.cloudreve.oauth import CloudreveOAuthError, CloudreveOAuthTokenStore, refresh_oauth_tokens
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
    refresh_token: str | None = None
    timeout: float = 20.0

    def __post_init__(self) -> None:
        settings = Settings.from_env()
        token_store = CloudreveOAuthTokenStore(settings.cloudreve_token_store_path)
        stored_tokens = token_store.load()
        if self.base_url is None:
            self.base_url = settings.cloudreve_base_url
        if self.token is None:
            self.token = stored_tokens.get("access_token") or settings.cloudreve_access_token or settings.cloudreve_token
        if self.refresh_token is None:
            self.refresh_token = stored_tokens.get("refresh_token") or settings.cloudreve_refresh_token

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

    def _raise_http_error(self, status_code: int, *, endpoint: str) -> None:
        message = f"Cloudreve HTTP {status_code} while calling {endpoint}."
        if endpoint == "/api/v4/file/events" and status_code == 502:
            message = (
                f"{message} The events stream usually needs a valid Cloudreve API bearer token. "
                "It also expects X-Cr-Client-Id to be a UUID. "
                "If CLOUDREVE_TOKEN came from /api/v4/session/authn, that value is only a WebAuthn "
                "challenge and cannot authenticate the worker."
            )
        raise CloudreveError(code=status_code, message=message)

    @staticmethod
    def _is_auth_status(status_code: int) -> bool:
        return status_code in {401, 40023}

    @staticmethod
    def _is_auth_code(code: int | None) -> bool:
        return code in {401, 40023}

    def refresh_access_token_sync(self) -> bool:
        if not self.refresh_token:
            return False
        settings = Settings.from_env()
        try:
            data = refresh_oauth_tokens(settings, self.refresh_token)
        except CloudreveOAuthError:
            return False
        access_token = data.get("access_token") if isinstance(data, dict) else None
        refresh_token = data.get("refresh_token") if isinstance(data, dict) else None
        if not access_token:
            return False
        self.token = access_token
        if refresh_token:
            self.refresh_token = refresh_token
        CloudreveOAuthTokenStore(settings.cloudreve_token_store_path).save(data)
        return True

    def _list_files_sync(self, uri: str) -> Any:
        """Synchronous helper – uses *requests* which works reliably with Cloudreve Pro v4.

        Cloudreve Pro v4 endpoint: GET /api/v4/file  (NOT /api/v4/file/list)
        Response shape: {"code": 0, "data": {"files": [...], "parent": {...}, ...}}
        Each file object has a ``path`` field with the full cloudreve:// URI.
        """
        url = f"{self.base_url}/api/v4/file"
        response = requests.get(url, params={"uri": uri}, headers=self._headers(), timeout=self.timeout)
        if self._is_auth_status(response.status_code) and self.refresh_access_token_sync():
            response = requests.get(url, params={"uri": uri}, headers=self._headers(), timeout=self.timeout)
        if response.status_code != 200:
            self._raise_http_error(response.status_code, endpoint="/api/v4/file")
        payload = response.json()
        code = payload.get("code")
        if code != 0:
            if self._is_auth_code(code) and self.refresh_access_token_sync():
                return self._list_files_sync(uri)
            raise CloudreveError(code=code, message=payload.get("msg") or "Unknown Cloudreve error")
        return payload.get("data")

    async def list_files(self, uri: str) -> Any:
        import asyncio
        return await asyncio.to_thread(self._list_files_sync, uri)

    def _get_metadata_sync(self, uri: str) -> Any:
        """Synchronous helper for file metadata.

        Cloudreve Pro v4 endpoint: GET /api/v4/file/info  (NOT /api/v4/file/metadata)
        """
        url = f"{self.base_url}/api/v4/file/info"
        response = requests.get(url, params={"uri": uri}, headers=self._headers(), timeout=self.timeout)
        if self._is_auth_status(response.status_code) and self.refresh_access_token_sync():
            response = requests.get(url, params={"uri": uri}, headers=self._headers(), timeout=self.timeout)
        if response.status_code != 200:
            self._raise_http_error(response.status_code, endpoint="/api/v4/file/info")
        payload = response.json()
        code = payload.get("code")
        if code != 0:
            if self._is_auth_code(code) and self.refresh_access_token_sync():
                return self._get_metadata_sync(uri)
            raise CloudreveError(code=code, message=payload.get("msg") or "Unknown Cloudreve error")
        return payload.get("data")

    async def get_metadata(self, uri: str) -> Any:
        import asyncio
        return await asyncio.to_thread(self._get_metadata_sync, uri)

    async def can_access(self, uri: str) -> bool:
        try:
            await self.get_metadata(uri)
            return True
        except CloudreveError as exc:
            if exc.code in {403, 404, 40044}:
                return False
            raise

    async def get_file_content(self, uri: str) -> bytes:
        """Download file content from Cloudreve (async wrapper over sync implementation)."""
        import asyncio
        return await asyncio.to_thread(self.get_file_content_sync, uri)

    def get_file_content_sync(self, uri: str) -> bytes:
        """Download file content from Cloudreve (synchronous)."""
        response = requests.get(
            f"{self.base_url}/api/v4/file/content",
            params={"uri": uri},
            headers=self._headers(),
            timeout=60.0,
        )
        if self._is_auth_status(response.status_code) and self.refresh_access_token_sync():
            response = requests.get(
                f"{self.base_url}/api/v4/file/content",
                params={"uri": uri},
                headers=self._headers(),
                timeout=60.0,
            )
        if response.status_code != 200:
            self._raise_http_error(response.status_code, endpoint="/api/v4/file/content")
        return response.content

    def _iter_file_events_sync(self, uri: str = "cloudreve://my", client_id: str | None = None) -> Iterator[dict[str, Any]]:
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        if client_id:
            headers["X-Cr-Client-Id"] = client_id
        url = f"{self.base_url}/api/v4/file/events"
        response = requests.get(url, params={"uri": uri}, headers=headers, stream=True, timeout=None)
        if self._is_auth_status(response.status_code) and self.refresh_access_token_sync():
            headers = self._headers()
            headers["Accept"] = "text/event-stream"
            if client_id:
                headers["X-Cr-Client-Id"] = client_id
            response = requests.get(url, params={"uri": uri}, headers=headers, stream=True, timeout=None)
        if response.status_code != 200:
            self._raise_http_error(response.status_code, endpoint="/api/v4/file/events")
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield {"raw": line.removeprefix("data: ")}

    async def iter_file_events(self, uri: str = "cloudreve://my", client_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        import asyncio
        import queue
        import threading
        
        event_queue: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        
        def _read_events():
            headers = self._headers()
            headers["Accept"] = "text/event-stream"
            if client_id:
                headers["X-Cr-Client-Id"] = client_id
            url = f"{self.base_url}/api/v4/file/events"
            try:
                response = requests.get(url, params={"uri": uri}, headers=headers, stream=True, timeout=None)
                if self._is_auth_status(response.status_code) and self.refresh_access_token_sync():
                    headers = self._headers()
                    headers["Accept"] = "text/event-stream"
                    if client_id:
                        headers["X-Cr-Client-Id"] = client_id
                    response = requests.get(url, params={"uri": uri}, headers=headers, stream=True, timeout=None)
                if response.status_code != 200:
                    try:
                        self._raise_http_error(response.status_code, endpoint="/api/v4/file/events")
                    except CloudreveError as exc:
                        event_queue.put(exc)
                    return
                event_queue.put({"type": "connected"})
                current_event_type = "message"
                for line in response.iter_lines(decode_unicode=True):
                    if stop_event.is_set():
                        break
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event_type = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data = line.split(":", 1)[1].strip()
                        event_queue.put({"type": current_event_type, "raw": data})
                        current_event_type = "message"
            except Exception as e:
                event_queue.put({"type": "error", "error": e})
            finally:
                event_queue.put(None)
        
        thread = threading.Thread(target=_read_events, daemon=True)
        thread.start()
        
        try:
            while True:
                event = await asyncio.get_event_loop().run_in_executor(None, event_queue.get)
                if event is None:
                    break
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            stop_event.set()
