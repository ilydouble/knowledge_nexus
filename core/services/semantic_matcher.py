"""Semantic Template Matcher.

Selects the most relevant Hyper-Extract YAML templates for a given document by
embedding both the document preview (filename + first ~1500 chars of text) and
each template's metadata (name, description, tags) with a shared embedding
service, then ranking by cosine similarity.

Typical usage::

    from core.services.embedding import BigModelEmbeddingService
    from core.services.semantic_matcher import SemanticTemplateMatcher

    svc = BigModelEmbeddingService(api_key="...")
    matcher = SemanticTemplateMatcher(embedding_service=svc)
    ontology = matcher.match(text="...", filename="report.pdf")
    # ontology is a merged {concepts, relations, instructions} dict
"""
from __future__ import annotations

import logging
import math
from typing import Any

from core.services.template_adapter import (
    HyperExtractTemplateAdapter,
    TemplateRecord,
    TemplateRegistry,
)

logger = logging.getLogger(__name__)

# Characters of document text fed into the query embedding (filename excluded).
_DOC_PREVIEW_CHARS: int = 1_500


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticTemplateMatcher:
    """Rank Hyper-Extract templates against a document using embedding cosine similarity.

    Template embeddings are computed once (lazily on first ``match()`` call) and
    cached in memory for the lifetime of this instance.

    Args:
        embedding_service: Any object with an ``embed_batch(texts) -> list[list[float]]``
            method (e.g. ``BigModelEmbeddingService`` or ``DeterministicEmbeddingService``).
        registry:          Template registry to discover templates from.
        adapter:           Adapter used to convert templates to ontologies.
        top_k:             Number of templates to fuse into the returned ontology.
        skip_prefixes:     Template ID prefixes to exclude (default: ``["nexus/"]``).
    """

    def __init__(
        self,
        embedding_service: Any,
        registry: TemplateRegistry | None = None,
        adapter: HyperExtractTemplateAdapter | None = None,
        top_k: int = 3,
        skip_prefixes: list[str] | None = None,
    ) -> None:
        self._svc = embedding_service
        self._registry = registry or TemplateRegistry()
        self._adapter = adapter or HyperExtractTemplateAdapter(registry=self._registry)
        self.top_k = top_k
        self._skip_prefixes: list[str] = skip_prefixes if skip_prefixes is not None else ["nexus/"]
        # Cache: template_id → (record, vector)
        self._template_vectors: dict[str, tuple[TemplateRecord, list[float]]] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match(self, text: str, filename: str = "") -> dict[str, Any] | None:
        """Return a merged ontology for the top-K templates matching *text*.

        Args:
            text:     Full document text (only the first ``_DOC_PREVIEW_CHARS``
                      chars are embedded).
            filename: Original filename for additional signal.

        Returns:
            Merged ``{concepts, relations, instructions}`` dict, or ``None``
            if embedding fails or no templates are found.
        """
        try:
            vectors = self._ensure_template_vectors()
        except Exception as exc:
            logger.warning("SemanticTemplateMatcher: template embedding failed: %s", exc)
            return None

        if not vectors:
            logger.warning("SemanticTemplateMatcher: no templates available to match")
            return None

        query = self._build_query(text, filename)
        try:
            query_vec = self._svc.embed_batch([query])[0]
        except Exception as exc:
            logger.warning("SemanticTemplateMatcher: document embedding failed: %s", exc)
            return None

        scored = sorted(
            ((tid, _cosine(query_vec, vec), rec) for tid, (rec, vec) in vectors.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        top = scored[: self.top_k]
        logger.info(
            "SemanticTemplateMatcher: top-%d templates: %s",
            self.top_k,
            [(tid, round(score, 3)) for tid, score, _ in top],
        )

        results = []
        for tid, _score, _rec in top:
            r = self._adapter.adapt_by_id(tid)
            if r is not None:
                results.append(r.ontology)

        return self._merge(results) if results else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_query(self, text: str, filename: str) -> str:
        preview = text[:_DOC_PREVIEW_CHARS].strip()
        parts = [p for p in (filename.strip(), preview) if p]
        return "\n\n".join(parts)

    def _ensure_template_vectors(self) -> dict[str, tuple[TemplateRecord, list[float]]]:
        if self._template_vectors is not None:
            return self._template_vectors

        records = [
            r for r in self._registry.list()
            if not any(r.template_id.startswith(p) for p in self._skip_prefixes)
        ]
        if not records:
            self._template_vectors = {}
            return self._template_vectors

        texts = [self._template_text(r) for r in records]
        vecs = self._svc.embed_batch(texts)
        self._template_vectors = {
            r.template_id: (r, v) for r, v in zip(records, vecs, strict=False)
        }
        logger.info("SemanticTemplateMatcher: embedded %d templates", len(records))
        return self._template_vectors

    @staticmethod
    def _template_text(record: TemplateRecord) -> str:
        parts = [record.name]
        if record.description:
            parts.append(record.description)
        if record.tags:
            parts.append("Tags: " + ", ".join(record.tags))
        return ". ".join(parts)

    @staticmethod
    def _merge(ontologies: list[dict[str, Any]]) -> dict[str, Any]:
        """Union of concepts/relations across multiple ontologies, deduped by key."""
        seen_concepts: set[str] = set()
        seen_relations: set[str] = set()
        concepts: list[dict] = []
        relations: list[dict] = []
        instructions_parts: list[str] = []

        for ont in ontologies:
            for c in ont.get("concepts", []):
                key = c.get("type", "")
                if key and key not in seen_concepts:
                    seen_concepts.add(key)
                    concepts.append(c)
            for r in ont.get("relations", []):
                key = r.get("relation", "")
                if key and key not in seen_relations:
                    seen_relations.add(key)
                    relations.append(r)
            instr = ont.get("instructions", "").strip()
            if instr and instr not in instructions_parts:
                instructions_parts.append(instr)

        return {
            "concepts": concepts or [{"type": "Entity", "description": "A named entity."}],
            "relations": relations or [{
                "relation": "RELATES_TO", "source": "Entity", "target": "Entity",
                "description": "General semantic relationship between entities",
            }],
            "instructions": " | ".join(instructions_parts) if instructions_parts
                            else "Extract named, specific entities only.",
        }
