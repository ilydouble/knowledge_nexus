"""ArtifactStore — write/read full parsed-text blobs to object storage.

Postgres only stores a ≤400-char preview in semantic_chunks.text.
Full parsed text lives here, referenced by semantic_documents.parsed_text_key
as an ``s3://<bucket>/<key>`` URI.

Two implementations:
- ``MinioArtifactStore``  — real MinIO / S3-compatible backend.
- ``NullArtifactStore``   — no-op fallback (parsed_text_key stays as-is).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Protocol

logger = logging.getLogger("core.storage.artifact_store")

_BUCKET_DEFAULT = "knowledge-nexus"
_PREFIX = "parsed-text"


class ArtifactStore(Protocol):
    """Minimal protocol for writing and reading text artifacts."""

    def write(self, content_hash: str, filename: str, text: str) -> str:
        """Persist *text* and return the canonical URI (e.g. ``s3://…``)."""
        ...

    def read(self, uri: str) -> str:
        """Return the full text for *uri* previously returned by ``write``."""
        ...


class NullArtifactStore:
    """No-op store used when MinIO is not configured.

    ``write`` returns the source URI unchanged so ``parsed_text_key`` still
    carries a meaningful pointer (the original local / cloudreve URI).
    """

    def write(self, content_hash: str, filename: str, text: str) -> str:  # noqa: ARG002
        return ""  # caller falls back to source URI

    def read(self, uri: str) -> str:
        raise NotImplementedError(f"NullArtifactStore cannot retrieve content for {uri!r}")


class MinioArtifactStore:
    """S3-compatible artifact store backed by MinIO.

    Object key layout::

        parsed-text/<sha256[:16]>/<filename>.txt

    The returned URI is ``s3://<bucket>/<key>``.

    Parameters
    ----------
    endpoint:
        MinIO server URL, e.g. ``http://localhost:9000``.
    access_key / secret_key:
        MinIO credentials.
    bucket:
        Target bucket name (auto-created if absent).
    secure:
        Whether to use TLS.  Derived automatically from *endpoint* when
        the URL starts with ``https://``.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str = _BUCKET_DEFAULT,
    ) -> None:
        from minio import Minio  # type: ignore[import-untyped]

        # Strip scheme — the Minio client wants only host[:port]
        host = endpoint.removeprefix("https://").removeprefix("http://")
        secure = endpoint.startswith("https://")

        self._client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket
        self._ensure_bucket()

    # ------------------------------------------------------------------
    def _ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("MinIO bucket '%s' created.", self._bucket)
        except Exception as exc:
            logger.warning("Could not ensure MinIO bucket '%s': %s", self._bucket, exc)

    def write(self, content_hash: str, filename: str, text: str) -> str:
        """Write *text* to MinIO and return ``s3://<bucket>/<key>``."""
        import io
        key = f"{_PREFIX}/{content_hash[:16]}/{filename}.txt"
        data = text.encode("utf-8")
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type="text/plain; charset=utf-8",
        )
        uri = f"s3://{self._bucket}/{key}"
        logger.debug("Artifact written: %s (%d bytes)", uri, len(data))
        return uri

    def read(self, uri: str) -> str:
        """Read and return the full text for an ``s3://`` URI."""
        if not uri.startswith("s3://"):
            raise ValueError(f"MinioArtifactStore can only read s3:// URIs, got: {uri!r}")
        # s3://<bucket>/<key>
        without_scheme = uri[len("s3://"):]
        bucket, _, key = without_scheme.partition("/")
        response = self._client.get_object(bucket, key)
        try:
            return response.read().decode("utf-8")
        finally:
            response.close()
            response.release_conn()


def build_artifact_store(
    endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str = _BUCKET_DEFAULT,
) -> MinioArtifactStore | NullArtifactStore:
    """Try to build a ``MinioArtifactStore``; fall back to ``NullArtifactStore``."""
    try:
        store = MinioArtifactStore(endpoint, access_key, secret_key, bucket)
        logger.info("MinioArtifactStore initialised (bucket=%s endpoint=%s)", bucket, endpoint)
        return store
    except Exception as exc:
        logger.warning("MinIO unavailable (%s); falling back to NullArtifactStore.", exc)
        return NullArtifactStore()
