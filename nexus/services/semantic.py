from __future__ import annotations

import re
from collections import Counter

from nexus.models import SemanticDocument, TextChunk
from nexus.repository import InMemoryRepository


STOP_WORDS = {
    "and",
    "the",
    "with",
    "uses",
    "this",
    "that",
    "from",
    "into",
    "project",
    "notes",
}


class TextParser:
    def __init__(self, chunk_size: int = 800) -> None:
        self.chunk_size = chunk_size

    def parse(self, uri: str, content: str, requested_by: str = "system") -> SemanticDocument:
        normalized = " ".join(content.split())
        chunks = [
            TextChunk(id=f"{uri}#chunk-{index}", text=chunk, index=index)
            for index, chunk in enumerate(self._chunk(normalized), start=1)
        ]
        return SemanticDocument(
            uri=uri,
            summary=self._summary(normalized),
            tags=self._tags(normalized),
            entities=self._entities(content),
            chunks=chunks,
            requested_by=requested_by,
        )

    def _chunk(self, text: str) -> list[str]:
        if not text:
            return [""]
        return [text[index : index + self.chunk_size] for index in range(0, len(text), self.chunk_size)]

    @staticmethod
    def _summary(text: str) -> str:
        if len(text) <= 160:
            return text
        return text[:157].rstrip() + "..."

    @staticmethod
    def _tags(text: str) -> list[str]:
        words = [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)]
        counts = Counter(word for word in words if word not in STOP_WORDS)
        return [word for word, _ in counts.most_common(8)]

    @staticmethod
    def _entities(text: str) -> list[str]:
        seen: set[str] = set()
        entities: list[str] = []
        for match in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text):
            if match not in seen:
                seen.add(match)
                entities.append(match)
        return entities


class SemanticProcessor:
    def __init__(self, repository: InMemoryRepository, parser: TextParser | None = None) -> None:
        self.repository = repository
        self.parser = parser or TextParser()

    def index_text(self, uri: str, content: str, requested_by: str) -> SemanticDocument:
        document = self.parser.parse(uri=uri, content=content, requested_by=requested_by)
        return self.repository.add_document(document)

