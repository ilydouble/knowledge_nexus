"""Document linker based on shared extracted entities and optional LLM typing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from nexus.models import KnowledgeLayer, KnowledgeLink, SemanticDocument
from nexus.repositories.base import NexusRepository
from nexus.services._llm_utils import extract_json_from_text
from nexus.settings import Settings

logger = logging.getLogger("nexus.doc_linker")

RELATION_TYPES: tuple[tuple[str, str], ...] = (
    ("引用", "文档A引用了文档B的内容或结论"),
    ("补充", "文档A补充了文档B未覆盖的细节或数据"),
    ("扩展", "文档A在文档B的基础上进行了扩展/延伸"),
    ("冲突", "文档A与文档B存在矛盾或不同结论"),
    ("相似", "文档A与文档B主题相似，无明确引用/补充/扩展关系"),
)


@dataclass(frozen=True)
class LinkResult:
    uri_a: str
    uri_b: str
    relation: str
    confidence: float
    reasoning: str = ""
    shared_entities: list[str] = field(default_factory=list)
    direction: str = "bidirectional"


class DocLinker:
    """Create document links for documents that share extracted entities."""

    def __init__(
        self,
        repository: NexusRepository,
        *,
        settings: Settings | None = None,
        api_key: str | None = None,
        http_client: Any | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.repository = repository
        self.settings = settings or Settings.from_env()
        self.api_key = api_key
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout

    def find_and_link_all(
        self,
        min_shared_entities: int = 1,
        uri_filter: list[str] | None = None,
    ) -> list[LinkResult]:
        """Find document pairs with shared entities and persist links."""
        documents = self._documents_with_entities(uri_filter)
        existing_pairs = self._existing_pairs()
        results: list[LinkResult] = []

        for left_index, doc_a in enumerate(documents):
            for doc_b in documents[left_index + 1 :]:
                pair_key = self._pair_key(doc_a.uri, doc_b.uri)
                if pair_key in existing_pairs:
                    continue
                shared = self._shared_entities(doc_a, doc_b)
                if len(shared) < min_shared_entities:
                    continue
                result = self._type_relationship(doc_a, doc_b, shared)
                self._persist_link(result)
                existing_pairs.add(pair_key)
                results.append(result)

        return results

    def _documents_with_entities(self, uri_filter: list[str] | None) -> list[SemanticDocument]:
        uri_set = set(uri_filter or [])
        documents = [
            document
            for document in self.repository.list_documents()
            if document.entities and (not uri_set or document.uri in uri_set)
        ]
        return sorted(documents, key=lambda document: document.uri)

    def _existing_pairs(self) -> set[tuple[str, str]]:
        return {
            self._pair_key(link.source_uri, link.target_uri)
            for link in self.repository.list_links()
            if link.created_by == "doc_linker"
        }

    def _shared_entities(self, doc_a: SemanticDocument, doc_b: SemanticDocument) -> list[str]:
        entities_a = {entity.casefold().strip() for entity in doc_a.entities if entity.strip()}
        entities_b = {entity.casefold().strip() for entity in doc_b.entities if entity.strip()}
        shared_keys = entities_a & entities_b

        original: dict[str, str] = {}
        for entity in [*doc_a.entities, *doc_b.entities]:
            key = entity.casefold().strip()
            if key and key not in original:
                original[key] = entity.strip()
        return [original[key] for key in sorted(shared_keys)][:10]

    def _type_relationship(
        self,
        doc_a: SemanticDocument,
        doc_b: SemanticDocument,
        shared_entities: list[str],
    ) -> LinkResult:
        if self.api_key:
            llm_result = self._type_with_llm(doc_a, doc_b, shared_entities)
            if llm_result is not None:
                return llm_result

        return LinkResult(
            uri_a=doc_a.uri,
            uri_b=doc_b.uri,
            relation="相似",
            confidence=0.3,
            reasoning="shared entities",
            shared_entities=shared_entities,
        )

    def _type_with_llm(
        self,
        doc_a: SemanticDocument,
        doc_b: SemanticDocument,
        shared_entities: list[str],
    ) -> LinkResult | None:
        relation_lines = "\n".join(f"- {name}: {description}" for name, description in RELATION_TYPES)
        prompt = f"""你是一个文档关系分析专家。请判断以下两篇文档之间的关系类型。

关系类型定义：
{relation_lines}

文档A：
  URI: {doc_a.uri}
  摘要: {doc_a.summary[:500]}

文档B：
  URI: {doc_b.uri}
  摘要: {doc_b.summary[:500]}

共享实体：{", ".join(shared_entities[:10])}

只返回 JSON：
{{"relation": "引用/补充/扩展/冲突/相似", "confidence": 0.0, "reasoning": "20字以内", "direction": "a_to_b / b_to_a / bidirectional"}}"""
        try:
            response = self.http_client.post(
                self.settings.llm_base_url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json={
                    "model": self.settings.llm_model,
                    "messages": [
                        {"role": "system", "content": "只返回合法 JSON，不要输出 markdown 或解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            for field in ("content", "reasoning"):
                parsed = extract_json_from_text(str(message.get(field, "")))
                if parsed:
                    return self._result_from_llm(doc_a, doc_b, shared_entities, parsed)
        except Exception as exc:
            logger.warning("Document relationship typing failed: %s", exc)
        return None

    def _result_from_llm(
        self,
        doc_a: SemanticDocument,
        doc_b: SemanticDocument,
        shared_entities: list[str],
        parsed: dict[str, Any],
    ) -> LinkResult:
        valid_relations = {name for name, _ in RELATION_TYPES}
        relation = str(parsed.get("relation", "相似")).strip()
        if relation not in valid_relations:
            relation = "相似"
        direction = str(parsed.get("direction", "bidirectional")).strip()
        if direction not in {"a_to_b", "b_to_a", "bidirectional"}:
            direction = "bidirectional"
        return LinkResult(
            uri_a=doc_a.uri,
            uri_b=doc_b.uri,
            relation=relation,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=str(parsed.get("reasoning", "")),
            shared_entities=shared_entities,
            direction=direction,
        )

    def _persist_link(self, result: LinkResult) -> None:
        self.repository.add_link(
            KnowledgeLink(
                source_uri=result.uri_a,
                target_uri=result.uri_b,
                relation=result.relation,
                layer=KnowledgeLayer.L3,
                owner_scope="system:doc_linker",
                source_file_uri=result.uri_a,
                visibility="team",
                created_by="doc_linker",
                note="Shared entities: " + ", ".join(result.shared_entities[:5]),
            )
        )

    def _pair_key(self, uri_a: str, uri_b: str) -> tuple[str, str]:
        return tuple(sorted((uri_a, uri_b)))
