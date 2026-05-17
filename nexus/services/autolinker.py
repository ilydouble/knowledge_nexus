from __future__ import annotations

from nexus.models import KnowledgeLayer, LinkSuggestion
from nexus.repository import InMemoryRepository


class AutoLinker:
    def __init__(self, repository: InMemoryRepository) -> None:
        self.repository = repository

    def suggest(self, source_uri: str) -> list[LinkSuggestion]:
        source = self.repository.get_document(source_uri)
        if source is None:
            return []
        source_tags = set(source.tags)
        suggestions: list[LinkSuggestion] = []
        for target in self.repository.list_documents():
            if target.uri == source_uri:
                continue
            shared_tags = source_tags.intersection(target.tags)
            if not shared_tags:
                continue
            score = len(shared_tags) / max(len(source_tags), 1)
            suggestions.append(
                LinkSuggestion(
                    source_uri=source_uri,
                    target_uri=target.uri,
                    layer=KnowledgeLayer.L3,
                    reason="shared tags: " + ", ".join(sorted(shared_tags)),
                    score=round(score, 3),
                )
            )
        return sorted(suggestions, key=lambda item: item.score, reverse=True)

