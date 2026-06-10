"""Build traceable, section-level context packages for downstream kgraph."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from nexus.services.content_parser import ParsedContent
from nexus.services.document_classifier import CATEGORIES, ClassificationResult
from nexus.services.knowledge_extractor import _EMERGENCY_FALLBACK_ONTOLOGY
from nexus.services.template_adapter import HyperExtractTemplateAdapter, TemplateRegistry, TemplateSelector


_PAGE_MARKER_RE = re.compile(r"---\s*Page\s+(\d+)\s*---", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_/\-.]{2,}|[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True)
class _ScoredSection:
    index: int
    text: str
    score: float
    start_char: int
    end_char: int
    page: int | None


class KGraphContextBuilder:
    """Create a compact JSON contract for graph extraction.

    The builder does pre-extraction filtering only. It preserves source and
    batch identifiers so later graph maintenance can replay or merge evidence.
    """

    def __init__(self, max_sections: int = 8, min_relevance_score: float = 0.2) -> None:
        self.max_sections = max_sections
        self.min_relevance_score = min_relevance_score

    def build(
        self,
        *,
        uri: str,
        parsed: ParsedContent,
        classification: ClassificationResult,
        extraction_batch_id: str | None = None,
    ) -> dict[str, Any]:
        document_id = self._document_id(uri)
        ontology_id = classification.doc_type
        business_domain = self._business_domain(classification.doc_type)
        registry = TemplateRegistry()
        selected_templates = TemplateSelector(registry).select(
            classification.doc_type,
            business_domain=business_domain,
        )

        # Resolve ontology via YAML adapter (nexus-v1 templates take priority).
        adapter = HyperExtractTemplateAdapter(registry=registry)
        adapter_result = adapter.adapt(classification.doc_type)
        if adapter_result is not None and not adapter_result.is_native_fallback:
            ontology = adapter_result.ontology
        else:
            # Try general fallback, then emergency Python dict
            general_result = adapter.adapt("general")
            ontology = (
                general_result.ontology
                if general_result is not None and not general_result.is_native_fallback
                else _EMERGENCY_FALLBACK_ONTOLOGY
            )
        template_meta = selected_templates[0].as_dict() if selected_templates else (
            adapter_result.template_meta if adapter_result is not None else {}
        )

        entity_hints = [item["type"] for item in ontology.get("concepts", []) if item.get("type")]
        relation_hints = [item["relation"] for item in ontology.get("relations", []) if item.get("relation")]

        scored = self._score_sections(parsed, classification, ontology)
        selected = [
            section
            for section in scored
            if section.score >= self.min_relevance_score
        ][: self.max_sections]
        if not selected and scored:
            selected = scored[:1]
        selected = sorted(selected, key=lambda section: section.index)

        return {
            "document_id": document_id,
            "source_id": uri,
            "extraction_batch_id": extraction_batch_id or str(uuid4()),
            "classification": {
                "doc_type": classification.doc_type,
                "business_domain": business_domain,
                "ontology_id": ontology_id,
                "primary_template_id": selected_templates[0].template_id if selected_templates else None,
                "primary_template_type": selected_templates[0].template_type if selected_templates else None,
                "selected_templates": [selection.as_dict() for selection in selected_templates],
                "strategy": classification.strategy,
                "confidence": classification.confidence,
                "signals": classification.signals,
                "should_extract": classification.strategy in {"llm_extract", "structural_summary"},
                "template_meta": template_meta,
            },
            "sections": [
                {
                    "section_id": f"{document_id}_section_{position}",
                    "title": self._section_title(section),
                    "relevance_score": round(section.score, 3),
                    "text": section.text,
                    "source_span": {
                        "page": section.page,
                        "start_char": section.start_char,
                        "end_char": section.end_char,
                    },
                    "entity_hints": entity_hints,
                    "relation_hints": relation_hints,
                }
                for position, section in enumerate(selected, start=1)
            ],
            "metadata": {
                "published_at": parsed.metadata.get("published_at"),
                "valid_from": parsed.metadata.get("valid_from"),
                "valid_to": parsed.metadata.get("valid_to"),
                "version": parsed.metadata.get("version"),
                "filename": parsed.metadata.get("filename"),
                "file_type": parsed.file_type,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        }

    def render_for_extraction(self, context: dict[str, Any]) -> str:
        """Render selected sections into a compact text block for LLM extraction."""
        sections = context.get("sections", [])
        if not sections:
            return ""
        blocks = []
        for section in sections:
            span = section.get("source_span", {})
            page = span.get("page")
            page_label = f"page={page}" if page is not None else "page=unknown"
            blocks.append(
                f"[{section['section_id']} | {page_label} | score={section['relevance_score']}]\n"
                f"{section['text']}"
            )
        return "\n\n".join(blocks)

    def _score_sections(
        self,
        parsed: ParsedContent,
        classification: ClassificationResult,
        ontology: dict[str, Any],
    ) -> list[_ScoredSection]:
        chunks = self._candidate_sections(parsed)
        terms = self._relevance_terms(classification, ontology)
        spans = self._chunk_spans(parsed.text, chunks)
        scored: list[_ScoredSection] = []
        max_raw = 1.0

        raw_scores: list[float] = []
        for chunk in chunks:
            lower = chunk.lower()
            raw = 0.0
            for term in terms:
                if term in lower:
                    raw += 2.0 if len(term) > 4 else 1.0
            raw += min(4.0, len(set(_TOKEN_RE.findall(chunk))) / 12)
            raw_scores.append(raw)
            max_raw = max(max_raw, raw)

        for index, (chunk, raw_score) in enumerate(zip(chunks, raw_scores, strict=True), start=1):
            start_char, end_char = spans[index - 1]
            score = raw_score / max_raw
            scored.append(
                _ScoredSection(
                    index=index,
                    text=chunk.strip(),
                    score=score,
                    start_char=start_char,
                    end_char=end_char,
                    page=self._page_for_offset(parsed.text, start_char),
                )
            )

        return sorted(scored, key=lambda section: (-section.score, section.index))

    def _candidate_sections(self, parsed: ParsedContent) -> list[str]:
        if len(parsed.chunks) > 1:
            return parsed.chunks
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", parsed.text)
            if paragraph.strip()
        ]
        if len(paragraphs) > 1:
            return paragraphs
        return parsed.chunks or ([parsed.text] if parsed.text.strip() else [])

    def _relevance_terms(self, classification: ClassificationResult, ontology: dict[str, Any]) -> set[str]:
        terms: set[str] = set()
        category = CATEGORIES.get(classification.doc_type, {})
        terms.update(term.lower() for term in category.get("filename_keywords", []))
        terms.update(term.lower() for term in category.get("content_keywords", []))

        for concept in ontology.get("concepts", []):
            terms.add(str(concept.get("type", "")).lower())
            terms.update(token.lower() for token in _TOKEN_RE.findall(str(concept.get("description", ""))))
        for relation in ontology.get("relations", []):
            terms.add(str(relation.get("relation", "")).lower())
            terms.update(token.lower() for token in _TOKEN_RE.findall(str(relation.get("description", ""))))

        terms.update(
            {
                "负责人",
                "负责",
                "部门",
                "系统",
                "依赖",
                "归属",
                "接口",
                "服务",
                "数据库",
                "api",
            }
        )
        return {term for term in terms if term}

    def _chunk_spans(self, text: str, chunks: list[str]) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        cursor = 0
        for chunk in chunks:
            stripped = chunk.strip()
            start = text.find(stripped, cursor)
            if start == -1:
                start = text.find(stripped)
            if start == -1:
                start = cursor
            end = start + len(stripped)
            spans.append((start, end))
            cursor = max(cursor, end)
        return spans

    def _page_for_offset(self, text: str, start_char: int) -> int | None:
        page: int | None = None
        for match in _PAGE_MARKER_RE.finditer(text):
            if match.start() > start_char:
                break
            page = int(match.group(1))
        return page

    def _section_title(self, section: _ScoredSection) -> str:
        if section.page is not None:
            return f"Page {section.page}"
        return f"Section {section.index}"

    def _document_id(self, uri: str) -> str:
        digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:12]
        return f"doc_{digest}"

    def _business_domain(self, doc_type: str) -> str:
        return {
            "academic_paper": "research",
            "technical_doc": "engineering",
            "meeting_minutes": "operations",
            "report": "business",
            "contract": "legal",
            "email": "communications",
            "tabular_data": "data",
            "general": "general",
        }.get(doc_type, "general")
