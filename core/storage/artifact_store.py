"""ArtifactStore — write/read full parsed-text blobs to object storage.

Postgres only stores a ≤400-char preview in semantic_chunks.text.
Full parsed text lives here, referenced by semantic_documents.parsed_text_key
as a URI:

- ``s3://<bucket>/<key>``          — MinIO / S3-compatible object storage.
- ``local:///abs/path/to/file``    — local filesystem fallback.

Three implementations:
- ``MinioArtifactStore``  — real MinIO / S3-compatible backend.
- ``LocalArtifactStore``  — local filesystem fallback; used when MinIO is
                            unavailable so ``parsed_text_key`` always points
                            to a readable location (never ``cloudreve://``).
- ``NullArtifactStore``   — no-op; kept for test stubs only.
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

    def delete(self, uri: str) -> None:
        """Delete the artifact at *uri*.  No-op if it does not exist."""
        ...


class NullArtifactStore:
    """No-op store for test stubs.  Not used in production."""

    def write(self, content_hash: str, filename: str, text: str) -> str:  # noqa: ARG002
        return ""  # signals the caller that no URI was produced

    def read(self, uri: str) -> str:
        raise NotImplementedError(f"NullArtifactStore cannot retrieve content for {uri!r}")

    def delete(self, uri: str) -> None:  # noqa: ARG002
        pass  # nothing to delete


class LocalArtifactStore:
    """Local-filesystem artifact store.

    Used as the MinIO fallback so ``parsed_text_key`` always resolves to a
    ``local://`` URI that the content endpoint can serve — even when the
    system is run without object storage.  This avoids ever writing a
    ``cloudreve://`` pointer as the canonical content address.

    File layout (mirrors MinIO key structure)::

        {base_dir}/parsed-text/{hash[:16]}/{filename}.txt

    The returned URI is ``local:///abs/path/to/file``.
    """

    def __init__(self, base_dir: str = "data/artifacts") -> None:
        import os
        self._base_dir = os.path.abspath(base_dir)

    def write(self, content_hash: str, filename: str, text: str) -> str:
        """Write *text* to the local filesystem and return a ``local://`` URI.

        The *filename* is sanitised with ``Path(...).name`` before it is
        embedded in the path so that values like ``../../etc/passwd`` or
        ``subdir/evil.txt`` cannot escape *base_dir*.
        """
        import os
        from pathlib import Path as _Path
        safe_name = _Path(filename).name or "artifact"
        rel_key = f"{_PREFIX}/{content_hash[:16]}/{safe_name}.txt"
        abs_path = os.path.join(self._base_dir, rel_key)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        uri = f"local://{abs_path}"
        logger.debug("Artifact written locally: %s (%d chars)", uri, len(text))
        return uri

    def read(self, uri: str) -> str:
        """Return the full text for a ``local://`` URI."""
        if not uri.startswith("local://"):
            raise ValueError(f"LocalArtifactStore can only read local:// URIs, got: {uri!r}")
        path = uri[len("local://"):]
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def delete(self, uri: str) -> None:
        """Remove the local file at *uri*.  Silently ignores missing files."""
        if not uri.startswith("local://"):
            return
        import os
        path = uri[len("local://"):]
        try:
            os.remove(path)
            logger.debug("Local artifact deleted: %s", uri)
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning("Could not delete local artifact %s: %s", uri, exc)


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
        """Verify MinIO is reachable and the target bucket exists (create if not).

        Exceptions are intentionally NOT caught here so that ``build_artifact_store``
        can detect an unreachable MinIO and fall back to ``LocalArtifactStore``.
        """
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            logger.info("MinIO bucket '%s' created.", self._bucket)

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

    def delete(self, uri: str) -> None:
        """Remove the object at *uri* (``s3://<bucket>/<key>``) from MinIO.

        Silently ignores missing objects or non-s3 URIs.
        """
        if not uri.startswith("s3://"):
            return  # local:// or cloudreve:// — nothing to delete in MinIO
        without_scheme = uri[len("s3://"):]
        bucket, _, key = without_scheme.partition("/")
        if not key:
            return
        try:
            self._client.remove_object(bucket, key)
            logger.debug("Artifact deleted: %s", uri)
        except Exception as exc:
            logger.warning("Could not delete artifact %s: %s", uri, exc)


def build_artifact_store(
    endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str = _BUCKET_DEFAULT,
    local_dir: str = "data/artifacts",
) -> MinioArtifactStore | LocalArtifactStore:
    """Try to build a ``MinioArtifactStore``; fall back to ``LocalArtifactStore``.

    The local fallback ensures ``parsed_text_key`` always resolves to a
    readable ``local://`` URI, never to a ``cloudreve://`` provenance pointer.
    """
    try:
        store = MinioArtifactStore(endpoint, access_key, secret_key, bucket)
        logger.info("MinioArtifactStore initialised (bucket=%s endpoint=%s)", bucket, endpoint)
        return store
    except Exception as exc:
        logger.warning(
            "MinIO unavailable (%s); falling back to LocalArtifactStore (dir=%s).",
            exc, local_dir,
        )
        return LocalArtifactStore(local_dir)
