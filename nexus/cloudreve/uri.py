from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class FileUri:
    raw: str
    scheme: str
    host: str
    user: str | None
    path: str
    query: str

    @classmethod
    def parse(cls, raw: str) -> "FileUri":
        parsed = urlparse(raw)
        if parsed.scheme != "cloudreve":
            raise ValueError("Cloudreve file URI must use the cloudreve scheme")
        if not parsed.hostname:
            raise ValueError("Cloudreve file URI must include a file-system host")
        return cls(
            raw=raw,
            scheme=parsed.scheme,
            host=parsed.hostname,
            user=parsed.username,
            path=parsed.path or "/",
            query=parsed.query,
        )

