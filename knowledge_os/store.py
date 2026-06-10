"""Compatibility exports for the old flat Knowledge OS store path."""

from knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from knowledge_os.infrastructure.store import KnowledgeOSStore

__all__ = [
    "InMemoryKnowledgeOSStore",
    "KnowledgeOSStore",
]
