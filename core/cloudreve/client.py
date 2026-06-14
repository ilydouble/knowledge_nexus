from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import requests

from core.cloudreve.oauth import CloudreveOAuthError, CloudreveOAuthTokenStore, refresh_oauth_tokens
from core.settings import Settings


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
    # Proactive refresh: if token expires within this many seconds, refresh before the request
    _token_expiry: datetime | None = field(default=None, repr=False, compare=False)
    _refresh_margin_seconds: int = field(default=120, repr=False, compare=False)

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
        # Parse stored expiry for proactive refresh
        if self._token_expiry is None:
            expiry_str = stored_tokens.get("access_expires")
            if expiry_str:
                try:
                    self._token_expiry = datetime.fromisoformat(expiry_str).astimezone(UTC)
                except ValueError:
                    pass

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
                "challenge and cannot authenticate the events stream."
            )
        raise CloudreveError(code=status_code, message=message)

    @staticmethod
    def _is_auth_status(status_code: int) -> bool:
        return status_code in {401, 403}

    @staticmethod
    def _is_auth_code(code: int | None) -> bool:
        # Cloudreve Pro v4 auth-related body codes:
        #   401    – generic login required
        #   40023  – token expired / invalid
        #   40081  – "failed to get target file: Login required" (download endpoint)
        return code in {401, 40023, 40081}

    def _token_needs_refresh(self) -> bool:
        """Return True if the access token is absent or expires within the refresh margin."""
        if not self.token:
            return True
        if self._token_expiry is None:
            return False  # No expiry info – assume valid
        return datetime.now(UTC) >= self._token_expiry - timedelta(seconds=self._refresh_margin_seconds)

    def refresh_access_token_sync(self) -> bool:
        """Refresh the access token using the stored refresh token.

        Returns True on success, False if the refresh token is missing or the
        server rejects it (e.g. code 40020 = token revoked).  In the latter
        case the caller should surface an error asking the user to re-authorize
        via /api/auth/cloudreve/start.
        """
        settings = Settings.from_env()
        # Always reload the latest refresh token from the file – this process
        # may have started with a stale in-memory token that has since
        # been rotated by another process (e.g. a test script or the API server).
        stored = CloudreveOAuthTokenStore(settings.cloudreve_token_store_path).load()
        fresh_rt = stored.get("refresh_token") or self.refresh_token
        if not fresh_rt:
            return False
        try:
            data = refresh_oauth_tokens(settings, fresh_rt)
        except CloudreveOAuthError:
            return False
        access_token = data.get("access_token") if isinstance(data, dict) else None
        if not access_token:
            return False
        self.token = access_token
        refresh_token = data.get("refresh_token") if isinstance(data, dict) else None
        if refresh_token:
            self.refresh_token = refresh_token
        # Update in-memory expiry from fresh response
        expiry_str = data.get("access_expires")
        if expiry_str:
            try:
                self._token_expiry = datetime.fromisoformat(expiry_str).astimezone(UTC)
            except ValueError:
                pass
        CloudreveOAuthTokenStore(settings.cloudreve_token_store_path).save(data)
        return True

    def ensure_fresh_token(self) -> None:
        """Proactively refresh the token if it is close to expiry.

        Called at the start of every API helper so we don't need to rely
        solely on reactive 401 handling mid-request.
        """
        if self._token_needs_refresh():
            self.refresh_access_token_sync()

    def _list_files_sync(self, uri: str) -> Any:
        """Synchronous helper – uses *requests* which works reliably with Cloudreve Pro v4.

        Cloudreve Pro v4 endpoint: GET /api/v4/file  (NOT /api/v4/file/list)
        Response shape: {"code": 0, "data": {"files": [...], "parent": {...}, ...}}
        Each file object has a ``path`` field with the full cloudreve:// URI.
        """
        self.ensure_fresh_token()
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
        self.ensure_fresh_token()
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

    def _get_download_url_sync(self, uri: str) -> str:
        """Get a signed download URL for *uri* via POST /api/v4/file/url.

        Cloudreve Pro v4 download flow:
          1. POST /api/v4/file/url  body: {"uris": [uri]}
             → {"code": 0, "data": {"urls": [{"url": "<signed-url>"}]}}
          2. GET <signed-url>  → raw file bytes
        """
        self.ensure_fresh_token()
        url = f"{self.base_url}/api/v4/file/url"
        resp = requests.post(url, json={"uris": [uri]}, headers=self._headers(), timeout=self.timeout)
        if self._is_auth_status(resp.status_code) and self.refresh_access_token_sync():
            resp = requests.post(url, json={"uris": [uri]}, headers=self._headers(), timeout=self.timeout)
        if resp.status_code != 200:
            self._raise_http_error(resp.status_code, endpoint="/api/v4/file/url")
        payload = resp.json()
        code = payload.get("code")
        if code != 0:
            if self._is_auth_code(code) and self.refresh_access_token_sync():
                return self._get_download_url_sync(uri)
            raise CloudreveError(code=code, message=payload.get("msg") or "Unknown Cloudreve error")
        urls = (payload.get("data") or {}).get("urls") or []
        if not urls or not urls[0].get("url"):
            raise CloudreveError(code=-1, message="No download URL returned by Cloudreve")
        return urls[0]["url"]

    def get_file_content_sync(self, uri: str) -> bytes:
        """Download file content from Cloudreve (synchronous).

        Uses the two-step Cloudreve Pro v4 download flow:
        1. Obtain a signed download URL via _get_download_url_sync()
        2. Stream the raw bytes from that URL in chunks so large files do not
           trigger a read-timeout on the single-response body read.
        """
        download_url = self._get_download_url_sync(uri)
        # Use stream=True so requests reads chunks instead of the whole body at
        # once.  connect_timeout=30s, read_timeout=120s per chunk.
        resp = requests.get(download_url, timeout=(30.0, 120.0), stream=True)
        if resp.status_code != 200:
            self._raise_http_error(resp.status_code, endpoint="/api/v4/file/content (signed)")
        chunks = []
        for chunk in resp.iter_content(chunk_size=1024 * 256):  # 256 KB per chunk
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)

    # ------------------------------------------------------------------
    # Upload (requires Files.Write scope)
    # ------------------------------------------------------------------

    def _upload_file_sync(
        self,
        content: bytes,
        filename: str,
        dest_uri: str,
        *,
        mime_type: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> Any:
        """Upload *content* to Cloudreve Pro v4 at *dest_uri*.

        The upload uses Cloudreve's two-step session flow:
          1. POST /api/v4/file/upload  — create an upload session.
          2. PUT  <session_upload_url> — stream the raw bytes.

        Parameters
        ----------
        content:   Raw bytes to upload.
        filename:  Name the file will have in Cloudreve.
        dest_uri:  Target folder URI, e.g. ``cloudreve://my/reports/``.
                   If *dest_uri* ends with the desired filename the folder
                   is inferred by stripping the last component.
        mime_type: MIME type hint (optional).
        overwrite: Whether to overwrite an existing file (default True).

        Returns the Cloudreve response data dict from the session endpoint.
        """
        import mimetypes as _mimetypes

        self.ensure_fresh_token()

        # Normalise dest_uri to a folder URI
        folder_uri = dest_uri if dest_uri.endswith("/") else dest_uri.rsplit("/", 1)[0] + "/"

        if not mime_type or mime_type == "application/octet-stream":
            guessed, _ = _mimetypes.guess_type(filename)
            if guessed:
                mime_type = guessed

        # Step 1 — create upload session
        init_url = f"{self.base_url}/api/v4/file/upload"
        init_payload = {
            "name": filename,
            "uri": folder_uri,
            "mime_type": mime_type,
            "size": len(content),
            "overwrite": overwrite,
        }
        resp = requests.post(init_url, json=init_payload, headers=self._headers(), timeout=self.timeout)
        if self._is_auth_status(resp.status_code) and self.refresh_access_token_sync():
            resp = requests.post(init_url, json=init_payload, headers=self._headers(), timeout=self.timeout)
        if resp.status_code != 200:
            self._raise_http_error(resp.status_code, endpoint="/api/v4/file/upload (init)")
        payload = resp.json()
        code = payload.get("code")
        if code != 0:
            if self._is_auth_code(code) and self.refresh_access_token_sync():
                return self._upload_file_sync(content, filename, dest_uri, mime_type=mime_type, overwrite=overwrite)
            raise CloudreveError(code=code, message=payload.get("msg") or "Upload session creation failed")

        session_data = payload.get("data") or {}
        upload_url: str | None = session_data.get("sessionID") and None  # Populated below

        # Cloudreve returns either a direct upload URL or a sessionID
        if "uploadURL" in session_data:
            upload_url = session_data["uploadURL"]
        elif "sessionID" in session_data:
            session_id = session_data["sessionID"]
            upload_url = f"{self.base_url}/api/v4/file/upload/{session_id}"

        if not upload_url:
            raise CloudreveError(code=-1, message="No upload URL returned by Cloudreve session endpoint")

        # Step 2 — PUT raw bytes to the upload URL
        put_headers = {"Content-Type": mime_type, "Content-Length": str(len(content))}
        # Some Cloudreve storage backends require the auth token on the PUT too
        if upload_url.startswith(self.base_url or ""):
            put_headers.update(self._headers())

        put_resp = requests.put(upload_url, data=content, headers=put_headers, timeout=(30.0, 300.0))
        if put_resp.status_code not in (200, 201, 204):
            self._raise_http_error(put_resp.status_code, endpoint=upload_url)

        return session_data

    async def upload_file(
        self,
        content: bytes,
        filename: str,
        dest_uri: str,
        *,
        mime_type: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> Any:
        """Async wrapper around :meth:`_upload_file_sync`."""
        import asyncio
        return await asyncio.to_thread(
            self._upload_file_sync, content, filename, dest_uri,
            mime_type=mime_type, overwrite=overwrite,
        )

    def _iter_file_events_sync(self, uri: str = "cloudreve://my", client_id: str | None = None) -> Iterator[dict[str, Any]]:
        self.ensure_fresh_token()
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
