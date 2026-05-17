"""File Gate — decides whether a file deserves processing before it is downloaded.

Rationale
---------
Not every file in Cloudreve contains text useful for knowledge extraction.
Blindly downloading and feeding binary blobs (images, videos, archives …)
to the LLM wastes bandwidth, tokens, and pollutes the graph with garbage nodes.

The Gate runs on the **filename / URI alone** — no download needed — and
returns one of three verdicts:

* ``processable``  — file type is fully supported; proceed with the pipeline.
* ``skipped``      — binary / media / archive; skip *permanently*, never retry.
* ``unsupported``  — office format or unknown extension we cannot parse yet;
                      skip for now (may be retried after parser support lands).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class GateVerdict(str, Enum):
    PROCESSABLE = "processable"
    SKIPPED     = "skipped"      # binary/media — permanent skip, no retry
    UNSUPPORTED = "unsupported"  # not-yet-supported — skip, may retry later


# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------

#: Fully parseable formats with reliable plain-text extraction.
_PROCESSABLE: frozenset[str] = frozenset({
    ".pdf", ".docx",
    ".txt", ".md", ".rst",
    ".csv", ".tsv",
    ".json", ".yaml", ".yml",
    ".xml",
    ".html", ".htm",
    # Excel — structural summary extraction via ExcelParser + tabular_data strategy
    ".xlsx", ".xls", ".xlsm",
})

#: Binary / media formats — no useful plain text; skip permanently.
_SKIP_BINARY: frozenset[str] = frozenset({
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".svg", ".ico", ".tiff", ".tif", ".heic", ".raw",
    # Video
    ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    # Audio
    ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma", ".opus",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z", ".xz", ".zst",
    # Executables & compiled
    ".exe", ".dll", ".so", ".dylib", ".bin", ".apk", ".ipa",
    # Disk images
    ".iso", ".dmg", ".img",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2",
    # Design files
    ".psd", ".ai", ".sketch", ".fig",
    # Databases
    ".db", ".sqlite", ".mdb",
})

#: Office formats / noisy logs we cannot parse yet — skip, not permanent.
_UNSUPPORTED: frozenset[str] = frozenset({
    ".pptx", ".ppt",
    ".odt", ".ods", ".odp",
    ".eml", ".msg",
    ".log",
})


# ---------------------------------------------------------------------------
# Gate types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateResult:
    """Immutable result returned by :class:`FileGate.check`."""

    verdict: GateVerdict
    reason: str
    extension: str

    @property
    def should_process(self) -> bool:
        """``True`` when the file should enter the full pipeline."""
        return self.verdict == GateVerdict.PROCESSABLE

    @property
    def permanent_skip(self) -> bool:
        """``True`` means never re-queue this URI (binary/media).
        ``False`` means it may be retried later."""
        return self.verdict == GateVerdict.SKIPPED


class FileGate:
    """Decide whether a file deserves processing based on its extension.

    The check is intentionally done **before** any download so that media
    files never hit the network layer.

    Usage::

        gate = FileGate()
        result = gate.check("photo.jpg")
        if not result.should_process:
            # mark job as skipped and move on
            ...
    """

    def check(self, filename: str) -> GateResult:
        """Return a :class:`GateResult` for *filename*.

        Only the file extension is examined; the file is never opened.
        """
        ext = Path(filename).suffix.lower()

        if ext in _PROCESSABLE:
            return GateResult(GateVerdict.PROCESSABLE, "supported file type", ext)

        if ext in _SKIP_BINARY:
            return GateResult(
                GateVerdict.SKIPPED,
                f"binary/media file — no extractable text ({ext})",
                ext,
            )

        if ext in _UNSUPPORTED:
            return GateResult(
                GateVerdict.UNSUPPORTED,
                f"parser not yet available for this format ({ext})",
                ext,
            )

        if not ext:
            return GateResult(
                GateVerdict.UNSUPPORTED,
                "file has no extension",
                ext,
            )

        return GateResult(
            GateVerdict.UNSUPPORTED,
            f"unknown extension — cannot determine if processable ({ext})",
            ext,
        )
