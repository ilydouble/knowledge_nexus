"""Knowledge Extractor - Extract structured knowledge from text using LLM."""

from __future__ import annotations

import concurrent.futures
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from core.services.template_adapter import HyperExtractTemplateAdapter
from core.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedKnowledge:
    """Result of knowledge extraction."""
    summary: str
    tags: list[str]
    entities: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    key_points: list[dict[str, Any]]
    confidence: float = 0.8
    raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Emergency Python fallback — used only if ALL YAML templates fail to load.
# Normal operation resolves ontology via HyperExtractTemplateAdapter (YAML).
# ---------------------------------------------------------------------------
_EMERGENCY_FALLBACK_ONTOLOGY: dict[str, Any] = {
    "concepts": [
        {"type": "Entity", "description": "A named entity in the document."},
    ],
    "relations": [
        {"relation": "RELATES_TO", "source": "Entity", "target": "Entity",
         "description": "General semantic association between entities"},
    ],
    "instructions": "Extract named, specific entities only. Avoid generic terms.",
}

# ---------------------------------------------------------------------------
# Map-Reduce thresholds
# ---------------------------------------------------------------------------
#: Characters fed to the LLM in single-pass mode.
_SINGLE_PASS_LIMIT: int = 12_000
#: Character budget per segment in map-reduce mode.
_SEGMENT_SIZE: int = 8_000
#: Overlap between adjacent segments to preserve context across boundaries.
_SEGMENT_OVERLAP: int = 400
#: Documents longer than this switch from single-pass to map-reduce.
_MAP_REDUCE_THRESHOLD: int = 10_000
#: Minimum entity confidence score; lower entries are dropped during merge.
MIN_ENTITY_CONFIDENCE: float = 0.5

# ---------------------------------------------------------------------------
# JSON Schema response formats (used with response_format={"type":"json_schema"})
# ---------------------------------------------------------------------------
_ENTITY_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id":          {"type": "string"},
        "label":       {"type": "string"},
        "type":        {"type": "string"},
        "description": {"type": "string"},
        "confidence":  {"type": "number"},
    },
    "required": ["id", "label", "type"],
}
_RELATION_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source":   {"type": "string"},
        "target":   {"type": "string"},
        "relation": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["source", "target", "relation"],
}
_KEY_POINT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content":    {"type": "string"},
        "type":       {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["content"],
}

def _make_json_schema(name: str, schema: dict) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}

#: Full extraction output schema (single-pass and map-reduce one-stage).
_EXTRACTION_JSON_SCHEMA: dict[str, Any] = _make_json_schema("extraction_result", {
    "type": "object",
    "properties": {
        "summary":    {"type": "string"},
        "tags":       {"type": "array", "items": {"type": "string"}},
        "entities":   {"type": "array", "items": _ENTITY_ITEM_SCHEMA},
        "relations":  {"type": "array", "items": _RELATION_ITEM_SCHEMA},
        "key_points": {"type": "array", "items": _KEY_POINT_ITEM_SCHEMA},
    },
    "required": ["summary", "tags", "entities", "relations", "key_points"],
})
#: Nodes-only schema for two-stage Stage-1.
_NODE_JSON_SCHEMA: dict[str, Any] = _make_json_schema("node_extraction_result", {
    "type": "object",
    "properties": {"entities": {"type": "array", "items": _ENTITY_ITEM_SCHEMA}},
    "required": ["entities"],
})
#: Edges-only schema for two-stage Stage-2.
_EDGE_JSON_SCHEMA: dict[str, Any] = _make_json_schema("edge_extraction_result", {
    "type": "object",
    "properties": {"relations": {"type": "array", "items": _RELATION_ITEM_SCHEMA}},
    "required": ["relations"],
})
#: Minimal schema for summary synthesis.
_SUMMARY_JSON_SCHEMA: dict[str, Any] = _make_json_schema("summary_result", {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
})


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------

def _cosine_sim(v1: list[float], v2: list[float]) -> float:
    """Cosine similarity between two float vectors (handles zero-norm safely)."""
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sum(a * a for a in v1) ** 0.5
    n2 = sum(b * b for b in v2) ** 0.5
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


class KnowledgeExtractor:
    """Extract structured knowledge from text using GLM-compatible chat completions."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        http_client: Any | None = None,
        timeout: float = 180.0,
        max_workers: int = 4,
        two_stage_extraction: bool = False,
        embedding_service: Any | None = None,
        semantic_dedup_threshold: float = 0.88,
    ) -> None:
        """Create a KnowledgeExtractor.

        Args:
            api_key: LLM API key (falls back to env vars).
            model: LLM model name.
            base_url: LLM chat-completions endpoint.
            http_client: Injected HTTP client (for testing).
            timeout: Per-request timeout seconds.
            max_workers: Parallel segment workers for map-reduce.
            two_stage_extraction: When True, map-reduce uses two LLM rounds
                (nodes first, then edges with node context) for higher relation
                accuracy.  Doubles LLM calls but improves precision.
            embedding_service: Optional service with ``embed_batch(texts)``
                for semantic entity deduplication after merge.
            semantic_dedup_threshold: Cosine-similarity threshold above which
                two entity labels are considered duplicates (default 0.88).
        """
        settings = Settings.from_env()
        self.api_key = api_key or settings.zhipu_api_key or settings.openai_api_key
        self.model = model or settings.llm_model
        self.base_url = base_url or settings.llm_base_url
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout
        self.max_workers = max_workers
        self.two_stage_extraction = two_stage_extraction
        self.embedding_service = embedding_service
        self.semantic_dedup_threshold = semantic_dedup_threshold
    
    def extract(
        self,
        text: str,
        doc_type: str = "general",
        ontology: dict | None = None,
        strategy: str = "llm_extract",
    ) -> ExtractedKnowledge:
        """Extract knowledge from text, routing by *strategy*.

        * ``"structural_summary"`` — lightweight schema extraction for tabular
          data (Excel / large CSV).  Sends the compact sheet/column summary to
          the LLM; never triggers map-reduce.
        * ``"llm_extract"`` (default) — full extraction, single-pass or
          map-reduce based on document length.

        Args:
            text:     The text content to extract knowledge from.
            doc_type: Category label (academic_paper, tabular_data, …).
            ontology: Custom ontology (uses default if not provided).
            strategy: Extraction strategy hint from the DocumentClassifier.

        Returns:
            ExtractedKnowledge with entities, relations, and summary.
        """
        if not self.api_key:
            return self._mock_extraction(text, doc_type)

        if ontology is None:
            ontology = self._get_ontology(doc_type)

        # ── Tabular / structural path ──────────────────────────────────────────
        if strategy == "structural_summary" or doc_type == "tabular_data":
            logger.info("Tabular extraction (structural summary), doc_type=%s", doc_type)
            return self._extract_tabular(text, ontology)

        # ── Standard LLM path ─────────────────────────────────────────────────
        if len(text) <= _MAP_REDUCE_THRESHOLD:
            # Single-pass: original behaviour, cap at _SINGLE_PASS_LIMIT
            prompt = self._build_extraction_prompt(text[:_SINGLE_PASS_LIMIT], ontology, doc_type)
            result = self._call_chat_completion(prompt)
            return self._normalize_result(result, doc_type)

        # Map-Reduce: long document
        logger.info(
            "Map-reduce extraction: %d chars, doc_type=%s", len(text), doc_type
        )
        return self._extract_mapreduce(text, doc_type, ontology)

    def _extract_tabular(self, structural_text: str, ontology: dict) -> ExtractedKnowledge:
        """Lightweight extraction for tabular data (Excel / large CSV).

        The input is a structural summary produced by ExcelParser, not raw
        cell values.  We ask the LLM to identify the dataset, its sheets,
        columns, and inferred domain — a single short LLM call suffices.
        """
        prompt = f"""You are analyzing the *schema* of a tabular dataset, NOT raw data.
The text below is a structural summary (sheet names, column headers, row counts, sample values).

Your task: extract high-level metadata entities — do NOT enumerate individual rows.

## Output Format (JSON)
{{
  "summary": "<1–2 sentence dataset description: name, domain, size>",
  "tags": ["<domain tag>", ...],
  "entities": [
    {{"id": "<type_label>", "label": "<name>", "type": "Dataset|Field|Sheet|DataType",
      "description": "<brief description>", "confidence": 0.9}}
  ],
  "relations": [
    {{"source": "<entity_id>", "target": "<entity_id>", "relation": "HAS_FIELD|BELONGS_TO_SHEET|HAS_TYPE",
      "confidence": 0.9}}
  ],
  "key_points": [
    {{"content": "<insight about the dataset>", "type": "fact"}}
  ]
}}

Rules:
- Create ONE Dataset entity for the whole workbook / file.
- Create ONE Sheet entity per worksheet (if multiple sheets).
- Create ONE Field entity per column.
- Add DataType entities only for clearly inferred types (e.g. "Date", "Currency", "Boolean").
- Keep relations: Dataset HAS_FIELD Field, Field BELONGS_TO_SHEET Sheet.
- Do not hallucinate columns that are not listed.

## Structural Summary
{structural_text[:6000]}
"""
        try:
            raw = self._call_chat_completion(prompt)
            return self._normalize_result(raw, "tabular_data")
        except Exception as exc:
            logger.warning("Tabular extraction failed: %s", exc)
            return ExtractedKnowledge(
                summary=structural_text[:300],
                tags=["tabular_data"],
                entities=[],
                relations=[],
                key_points=[],
                raw_response={"error": str(exc)},
            )

    def _call_chat_completion(
        self,
        prompt: str,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the LLM chat-completions endpoint and return parsed JSON.

        Args:
            prompt: User-turn content.
            response_format: OpenAI-compatible response_format dict.
                Defaults to ``_EXTRACTION_JSON_SCHEMA`` (json_schema mode).
                Pass ``{"type": "json_object"}`` for free-form JSON calls.
        """
        if response_format is None:
            response_format = _EXTRACTION_JSON_SCHEMA
        response = self.http_client.post(
            self.base_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                "response_format": response_format,
                "temperature": 0.2,
                "max_tokens": 4096,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)

    # ------------------------------------------------------------------
    # Map-Reduce helpers
    # ------------------------------------------------------------------

    def _split_text(self, text: str) -> list[str]:
        """Split *text* into overlapping segments for map-reduce extraction."""
        segments: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + _SEGMENT_SIZE, len(text))
            segments.append(text[start:end])
            if end >= len(text):
                break
            start = end - _SEGMENT_OVERLAP
        return segments

    def _extract_mapreduce(
        self, text: str, doc_type: str, ontology: dict
    ) -> ExtractedKnowledge:
        """Extract knowledge from a long document via concurrent map-reduce.

        Dispatches to one-stage (default) or two-stage mode depending on
        ``self.two_stage_extraction``.  Both paths use ``ThreadPoolExecutor``
        for parallel LLM calls and defer relation pruning until after the
        global merge so cross-segment relations are preserved.
        """
        segments = self._split_text(text)
        logger.info(
            "Map-reduce: %d segments × ~%d chars (workers=%d, two_stage=%s)",
            len(segments), _SEGMENT_SIZE, self.max_workers, self.two_stage_extraction,
        )

        if self.two_stage_extraction:
            partials = self._extract_two_stage(segments, doc_type, ontology)
        else:
            partials = self._extract_one_stage(segments, doc_type, ontology)

        if not partials:
            logger.warning("All segments failed; falling back to single-pass")
            prompt = self._build_extraction_prompt(text[:_SINGLE_PASS_LIMIT], ontology, doc_type)
            raw = self._call_chat_completion(prompt)
            return self._normalize_result(raw, doc_type)

        return self._merge_extractions(partials)

    # ------------------------------------------------------------------
    # One-stage concurrent extraction
    # ------------------------------------------------------------------

    def _extract_one_stage(
        self, segments: list[str], doc_type: str, ontology: dict
    ) -> list[ExtractedKnowledge]:
        """Extract entities+relations for each segment in one concurrent LLM round."""
        n = len(segments)

        def _process(args: tuple[int, str]) -> ExtractedKnowledge:
            i, segment = args
            prompt = self._build_extraction_prompt(segment, ontology, doc_type)
            raw = self._call_chat_completion(prompt)
            partial = self._normalize_result(raw, doc_type, prune_dangling_relations=False)
            logger.debug("Seg %d/%d: %d entities, %d relations",
                         i + 1, n, len(partial.entities), len(partial.relations))
            return partial

        partials: list[ExtractedKnowledge] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            fut_idx = {pool.submit(_process, (i, seg)): i for i, seg in enumerate(segments)}
            for fut in concurrent.futures.as_completed(fut_idx):
                i = fut_idx[fut]
                try:
                    partials.append(fut.result())
                except Exception as exc:
                    logger.warning("Seg %d/%d failed: %s", i + 1, n, exc)
        return partials

    # ------------------------------------------------------------------
    # Two-stage concurrent extraction
    # ------------------------------------------------------------------

    def _extract_two_stage(
        self, segments: list[str], doc_type: str, ontology: dict
    ) -> list[ExtractedKnowledge]:
        """Two-round extraction: nodes first, then edges with node context.

        Round 1 — concurrent node extraction across all segments.
        Round 2 — concurrent edge extraction; each segment receives its own
                  extracted nodes as ``known_nodes`` context, preventing the
                  LLM from hallucinating endpoints.

        Cross-segment relation pruning is deferred to ``_merge_extractions``.
        """
        n = len(segments)

        # ── Round 1: parallel node extraction ─────────────────────────────────
        def _extract_nodes(args: tuple[int, str]) -> tuple[int, list[dict]]:
            i, segment = args
            raw = self._call_chat_completion(
                self._build_node_prompt(segment, ontology, doc_type), _NODE_JSON_SCHEMA
            )
            entities = raw.get("entities", [])
            for e in entities:  # ensure stable IDs
                if not e.get("id"):
                    e["id"] = (
                        f"{e.get('type', 'concept').lower()}_"
                        f"{e.get('label', 'unknown').lower().replace(' ', '_')}"
                    )
            entities = [e for e in entities if float(e.get("confidence", 1.0)) >= MIN_ENTITY_CONFIDENCE]
            logger.debug("Two-stage R1 seg %d/%d: %d nodes", i + 1, n, len(entities))
            return i, entities

        seg_entities: dict[int, list[dict]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futs = {pool.submit(_extract_nodes, (i, seg)): i for i, seg in enumerate(segments)}
            for fut in concurrent.futures.as_completed(futs):
                i = futs[fut]
                try:
                    _, ents = fut.result()
                    seg_entities[i] = ents
                except Exception as exc:
                    logger.warning("Two-stage R1 seg %d failed: %s", i + 1, exc)
                    seg_entities[i] = []

        # ── Round 2: parallel edge extraction (node-context-aware) ────────────
        def _extract_edges(args: tuple[int, str, list[dict]]) -> tuple[int, list[dict]]:
            i, segment, entities = args
            raw = self._call_chat_completion(
                self._build_edge_prompt(segment, ontology, doc_type, entities), _EDGE_JSON_SCHEMA
            )
            relations = raw.get("relations", [])
            logger.debug("Two-stage R2 seg %d/%d: %d edges", i + 1, n, len(relations))
            return i, relations

        seg_relations: dict[int, list[dict]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futs = {
                pool.submit(_extract_edges, (i, seg, seg_entities.get(i, []))): i
                for i, seg in enumerate(segments)
            }
            for fut in concurrent.futures.as_completed(futs):
                i = futs[fut]
                try:
                    _, rels = fut.result()
                    seg_relations[i] = rels
                except Exception as exc:
                    logger.warning("Two-stage R2 seg %d failed: %s", i + 1, exc)
                    seg_relations[i] = []

        return [
            ExtractedKnowledge(
                summary="",  # synthesised in _merge_extractions if any segment has one
                tags=[],
                entities=seg_entities.get(i, []),
                relations=seg_relations.get(i, []),
                key_points=[],
                confidence=0.8,
            )
            for i in range(n)
        ]

    def _build_node_prompt(self, text: str, ontology: dict, doc_type: str) -> str:
        """Stage-1 prompt: extract entities only (no relations)."""
        concept_lines = [
            f"- **{c['type']}**: {c.get('description', '')}"
            for c in ontology.get("concepts", [])
        ]
        concepts_block = "\n".join(concept_lines) or "- Entity: any named item"
        instructions = ontology.get("instructions", "Extract named, specific entities only.")

        return f"""Extract ALL entities/nodes from the text. Do NOT extract relations yet.

## Document Type: {doc_type}

## Entity Types (use ONLY these; unknown types → "Concept")
{concepts_block}

## Extraction Instructions
{instructions}

## Output (JSON only)
{{
  "entities": [
    {{"id": "<type_lower>_<label_snake>", "label": "Display Name",
      "type": "EntityType", "description": "one sentence", "confidence": 0.9}}
  ]
}}

Rules:
1. IDs: lowercase(type) + "_" + snake_case(label).
2. confidence < 0.8 when uncertain; entries < 0.5 are discarded automatically.

## Text
{text}
"""

    def _build_edge_prompt(
        self,
        text: str,
        ontology: dict,
        doc_type: str,
        known_entities: list[dict],
    ) -> str:
        """Stage-2 prompt: extract relations between known nodes only."""
        relation_lines = [
            f"- **{r['relation']}**: {r.get('source', 'Entity')} → "
            f"{r.get('target', 'Entity')}  _{r.get('description', '')}_"
            for r in ontology.get("relations", [])
        ]
        relations_block = "\n".join(relation_lines) or "- RELATES_TO: Entity → Entity"

        node_lines = (
            "\n".join(f"- {e['id']} ({e.get('label', '')})" for e in known_entities)
            if known_entities
            else "(no entities identified in this segment)"
        )

        return f"""Extract relations between the known entities below. Do NOT create new entities.

## Document Type: {doc_type}

## Known Entities — endpoints MUST be IDs from this list
{node_lines}

## Relation Types (use ONLY these)
{relations_block}

## Output (JSON only)
{{
  "relations": [
    {{"source": "<entity_id>", "target": "<entity_id>",
      "relation": "RELATION_TYPE", "evidence": "brief quote or paraphrase"}}
  ]
}}

Rules:
1. source and target MUST be IDs from the Known Entities list above.
2. Use ONLY the listed relation types.
3. Only assert relations clearly stated or strongly implied — no hallucination.

## Text
{text}
"""

    def _merge_extractions(
        self, results: list[ExtractedKnowledge]
    ) -> ExtractedKnowledge:
        """Merge partial extractions: deduplicate entities and relations."""
        # Entities — deduplicate by ID (stable: type_label), first occurrence wins
        seen_ids: dict[str, dict] = {}
        for r in results:
            for entity in r.entities:
                eid = entity.get("id", "")
                if eid and eid not in seen_ids:
                    seen_ids[eid] = entity
        merged_entities = list(seen_ids.values())

        # Relations — deduplicate by (source, target, relation) tuple
        seen_rel_keys: set[tuple[str, str, str]] = set()
        merged_relations: list[dict] = []
        for r in results:
            for rel in r.relations:
                key = (
                    rel.get("source", ""),
                    rel.get("target", ""),
                    rel.get("relation", ""),
                )
                if key not in seen_rel_keys:
                    seen_rel_keys.add(key)
                    merged_relations.append(rel)

        # Global dangling-edge pruning: after merging ALL segments we now have
        # the complete entity set, so cross-segment edges are no longer falsely
        # pruned (e.g. entity A in seg-1 ↔ entity B in seg-2 are both present).
        all_entity_ids = {e["id"] for e in merged_entities}
        before = len(merged_relations)
        merged_relations = [
            rel for rel in merged_relations
            if rel.get("source", "") in all_entity_ids
            and rel.get("target", "") in all_entity_ids
        ]
        dropped = before - len(merged_relations)
        if dropped:
            logger.info("Global edge pruning: dropped %d dangling relation(s)", dropped)

        # Tags — ordered union, max 20
        seen_tags: set[str] = set()
        merged_tags: list[str] = []
        for r in results:
            for tag in r.tags:
                if tag.lower() not in seen_tags:
                    seen_tags.add(tag.lower())
                    merged_tags.append(tag)
                    if len(merged_tags) >= 20:
                        break

        # Key points — all, capped at 10
        merged_kp = [kp for r in results for kp in r.key_points][:10]

        # Summary — synthesise or take first
        summaries = [r.summary for r in results if r.summary.strip()]
        final_summary = (
            self._synthesize_summary(summaries) if len(summaries) > 1
            else (summaries[0] if summaries else "")
        )

        merged = ExtractedKnowledge(
            summary=final_summary,
            tags=merged_tags,
            entities=merged_entities,
            relations=merged_relations,
            key_points=merged_kp,
            confidence=min(r.confidence for r in results),
        )

        # ── Optional semantic deduplication ───────────────────────────────────
        if self.embedding_service is not None:
            merged = self._semantic_dedup(merged)

        return merged

    def _semantic_dedup(self, knowledge: ExtractedKnowledge) -> ExtractedKnowledge:
        """Merge near-duplicate entities using embedding cosine similarity.

        Entities whose label embeddings exceed ``self.semantic_dedup_threshold``
        are clustered via Union-Find and merged into the highest-confidence
        representative.  All relation endpoints are remapped to canonical IDs,
        and a final dangling-edge prune is performed afterwards.
        """
        entities = knowledge.entities
        if len(entities) < 2:
            return knowledge

        labels = [e.get("label", e.get("id", "")) for e in entities]
        try:
            vectors = self.embedding_service.embed_batch(labels)
        except Exception as exc:
            logger.warning("Semantic dedup skipped (embedding failed): %s", exc)
            return knowledge

        n = len(entities)
        parent = list(range(n))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(x: int, y: int) -> None:
            px, py = _find(x), _find(y)
            if px != py:
                parent[px] = py

        for i in range(n):
            for j in range(i + 1, n):
                if _cosine_sim(vectors[i], vectors[j]) >= self.semantic_dedup_threshold:
                    _union(i, j)

        # Group indices by cluster root
        clusters: dict[int, list[int]] = {}
        for i in range(n):
            clusters.setdefault(_find(i), []).append(i)

        merged_entities: list[dict] = []
        id_map: dict[str, str] = {}  # old_id → canonical_id

        for members in clusters.values():
            if len(members) == 1:
                merged_entities.append(entities[members[0]])
                continue
            best = max(members, key=lambda i: float(entities[i].get("confidence", 0.8)))
            canonical = entities[best]
            canonical_id = canonical["id"]
            for m in members:
                old_id = entities[m]["id"]
                if old_id != canonical_id:
                    id_map[old_id] = canonical_id
            merged_entities.append(canonical)

        if not id_map:
            return knowledge  # nothing was merged

        logger.info("Semantic dedup: merged %d duplicate entity/entities", len(id_map))

        # Remap relation endpoints + deduplicate
        seen_keys: set[tuple[str, str, str]] = set()
        new_relations: list[dict] = []
        for rel in knowledge.relations:
            src = id_map.get(rel.get("source", ""), rel.get("source", ""))
            tgt = id_map.get(rel.get("target", ""), rel.get("target", ""))
            key = (src, tgt, rel.get("relation", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                new_relations.append({**rel, "source": src, "target": tgt})

        # Final dangling-edge prune after ID remapping
        all_ids = {e["id"] for e in merged_entities}
        new_relations = [
            r for r in new_relations
            if r.get("source", "") in all_ids and r.get("target", "") in all_ids
        ]

        return ExtractedKnowledge(
            summary=knowledge.summary,
            tags=knowledge.tags,
            entities=merged_entities,
            relations=new_relations,
            key_points=knowledge.key_points,
            confidence=knowledge.confidence,
        )

    def _synthesize_summary(self, summaries: list[str]) -> str:
        """Ask the LLM to unify segment summaries into one coherent paragraph."""
        combined = "\n\n".join(
            f"[Part {i + 1}] {s}" for i, s in enumerate(summaries)
        )
        prompt = (
            "The following are summaries of consecutive sections of a single document.\n"
            "Write ONE concise summary (2-3 sentences) capturing the main topic and key conclusions.\n\n"
            f"{combined}\n\n"
            'Return JSON: {"summary": "unified summary here"}'
        )
        try:
            result = self._call_chat_completion(prompt, _SUMMARY_JSON_SCHEMA)
            return result.get("summary", summaries[0])
        except Exception:
            return summaries[0]

    def _get_ontology(self, doc_type: str) -> dict:
        """Return the ontology for *doc_type* via the YAML template adapter.

        Resolution order:
        1. nexus-v1 YAML template for the exact doc_type  → fully adapted ontology.
        2. nexus-v1 YAML template for 'general'           → broad fallback ontology.
        3. _EMERGENCY_FALLBACK_ONTOLOGY                   → last resort (YAML missing).

        Each returned dict contains:
        - ``concepts``: list of {type, description}
        - ``relations``: list of {relation, source, target, description}
        - ``instructions``: extraction guidance string
        """
        adapter = HyperExtractTemplateAdapter()
        result = adapter.adapt(doc_type)
        if result is not None and not result.is_native_fallback:
            logger.debug("Using YAML template ontology for doc_type=%s", doc_type)
            return result.ontology

        if doc_type != "general":
            general = adapter.adapt("general")
            if general is not None and not general.is_native_fallback:
                logger.debug("Falling back to general ontology for doc_type=%s", doc_type)
                return general.ontology

        logger.warning("No YAML template found for doc_type=%s; using emergency fallback", doc_type)
        return _EMERGENCY_FALLBACK_ONTOLOGY
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for extraction."""
        return """You are a knowledge extraction expert. Your task is to analyze documents and extract structured knowledge in JSON format.

You must identify:
1. **Summary**: A concise summary of the document (2-3 sentences)
2. **Tags**: 5-10 relevant keywords or tags
3. **Entities**: Important entities mentioned (people, organizations, projects, technologies, concepts, etc.)
4. **Relations**: Relationships between entities
5. **Key Points**: Important facts, conclusions, or insights

Always respond with valid JSON following the specified schema."""
    
    def _build_extraction_prompt(self, text: str, ontology: dict, doc_type: str) -> str:
        """Build an extraction prompt that includes per-type entity descriptions,
        relation source→target constraints, and document-specific instructions."""

        # ── Entity types section ──────────────────────────────────────────────
        concept_lines = []
        for c in ontology.get("concepts", []):
            desc = c.get("description", "")
            concept_lines.append(f"- **{c['type']}**: {desc}")
        concepts_block = "\n".join(concept_lines) if concept_lines else "- Entity: any named item"

        # ── Relation types section (with source → target) ─────────────────────
        relation_lines = []
        for r in ontology.get("relations", []):
            src = r.get("source", "Entity")
            tgt = r.get("target", "Entity")
            desc = r.get("description", "")
            relation_lines.append(f"- **{r['relation']}**: {src} → {tgt}  _{desc}_")
        relations_block = "\n".join(relation_lines) if relation_lines else "- RELATES_TO: Entity → Entity"

        # ── Per-type extraction instructions ─────────────────────────────────
        instructions = ontology.get("instructions", "Extract named, specific entities only.")

        return f"""Analyze the following document and extract structured knowledge.

## Document Type: {doc_type}

## Entity Types  ← use ONLY these; use "Concept" for anything that doesn't fit
{concepts_block}

## Relation Types  ← use ONLY these; respect the source → target direction
{relations_block}

## Extraction Instructions
{instructions}

## Output Format (respond with valid JSON only)
{{
  "summary": "2–3 sentence summary of the document",
  "tags": ["tag1", "tag2"],
  "entities": [
    {{
      "id": "<type_lower>_<label_snake_case>",
      "label": "Display Name",
      "type": "EntityType",
      "description": "One sentence description",
      "confidence": 0.9
    }}
  ],
  "relations": [
    {{
      "source": "<entity_id>",
      "target": "<entity_id>",
      "relation": "RELATION_TYPE",
      "evidence": "brief quote or paraphrase from text"
    }}
  ],
  "key_points": [
    {{
      "content": "Key insight or fact",
      "type": "conclusion|recommendation|fact",
      "confidence": 0.9
    }}
  ]
}}

## Rules
1. Use ONLY the entity types listed above. Unknown types → use "Concept".
2. Use ONLY the relation types listed above; respect the source → target direction.
3. IDs must be stable: lowercase(type) + "_" + lowercase(label with spaces→underscores).
4. Only create relations whose endpoints both exist in the entities list.
5. Only assert relations clearly stated or strongly implied — no hallucination.
6. Set confidence < 0.8 when uncertain; entities below 0.5 will be discarded.

## Document Content
{text}
"""
    
    def _normalize_result(
        self,
        result: dict,
        doc_type: str,
        prune_dangling_relations: bool = True,
    ) -> ExtractedKnowledge:
        """Normalize, validate, and quality-filter the raw LLM extraction result.

        Args:
            result: Raw dict from the LLM JSON response.
            doc_type: Document category label.
            prune_dangling_relations: When ``True`` (default, used for single-pass
                and tabular paths) drop relations whose endpoints are absent from
                this result's entity list.  Set to ``False`` during map-reduce
                segment processing so cross-segment relations are not discarded
                prematurely; ``_merge_extractions`` performs a global prune after
                all segments are merged.
        """
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        # Ensure every entity has a stable ID
        for entity in entities:
            if "id" not in entity or not entity["id"]:
                label = entity.get("label", "unknown")
                etype = entity.get("type", "Concept")
                entity["id"] = f"{etype.lower()}_{label.lower().replace(' ', '_')}"

        # Quality filter: drop entities below confidence threshold
        entities = [
            e for e in entities
            if float(e.get("confidence", 1.0)) >= MIN_ENTITY_CONFIDENCE
        ]

        # Quality filter: drop relations whose endpoints were removed
        # (only for single-pass; map-reduce defers this to _merge_extractions)
        if prune_dangling_relations:
            entity_ids = {e["id"] for e in entities}
            valid_relations = [
                rel for rel in relations
                if rel.get("source", "") in entity_ids and rel.get("target", "") in entity_ids
            ]
        else:
            valid_relations = relations

        return ExtractedKnowledge(
            summary=result.get("summary", ""),
            tags=result.get("tags", []),
            entities=entities,
            relations=valid_relations,
            key_points=result.get("key_points", []),
            confidence=result.get("confidence", 0.8),
            raw_response=result,
        )
    
    def _mock_extraction(self, text: str, doc_type: str) -> ExtractedKnowledge:
        """Return mock extraction when no LLM available."""
        # Simple rule-based extraction
        words = text.lower().split()
        word_freq = {}
        for word in words:
            if len(word) > 4:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        tags = sorted(word_freq.keys(), key=lambda w: word_freq[w], reverse=True)[:8]
        
        return ExtractedKnowledge(
            summary=text[:200] + "..." if len(text) > 200 else text,
            tags=tags,
            entities=[],
            relations=[],
            key_points=[],
            confidence=0.5,
            raw_response={"mock": True},
        )
    
    def get_document_type_suggestions(self, filename: str, text_preview: str) -> str:
        """Suggest document type based on filename and content."""
        filename_lower = filename.lower()
        
        if any(kw in filename_lower for kw in ["paper", "论文", "research", "study"]):
            return "academic_paper"
        if any(kw in filename_lower for kw in ["api", "技术", "tech", "doc", "readme"]):
            return "technical_doc"
        if any(kw in filename_lower for kw in ["meeting", "会议", "minutes"]):
            return "meeting_minutes"
        if any(kw in filename_lower for kw in ["report", "报告", "月报", "周报"]):
            return "report"
        
        return "general"
