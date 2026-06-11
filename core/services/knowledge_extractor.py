"""Knowledge Extractor - Extract structured knowledge from text using LLM."""

from __future__ import annotations

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

class KnowledgeExtractor:
    """Extract structured knowledge from text using GLM-compatible chat completions."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        http_client: Any | None = None,
        timeout: float = 180.0,
    ) -> None:
        settings = Settings.from_env()
        self.api_key = api_key or settings.zhipu_api_key or settings.openai_api_key
        self.model = model or settings.llm_model
        self.base_url = base_url or settings.llm_base_url
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout
    
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

    def _call_chat_completion(self, prompt: str) -> dict[str, Any]:
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
                "response_format": {"type": "json_object"},
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
        """Extract knowledge from a long document via map-reduce."""
        segments = self._split_text(text)
        logger.info(
            "Map-reduce: %d segments × ~%d chars each",
            len(segments),
            _SEGMENT_SIZE,
        )

        partials: list[ExtractedKnowledge] = []
        for i, segment in enumerate(segments):
            try:
                prompt = self._build_extraction_prompt(segment, ontology, doc_type)
                raw = self._call_chat_completion(prompt)
                partial = self._normalize_result(raw, doc_type)
                partials.append(partial)
                logger.debug(
                    "Segment %d/%d: %d entities, %d relations",
                    i + 1, len(segments),
                    len(partial.entities), len(partial.relations),
                )
            except Exception as exc:
                logger.warning("Segment %d/%d failed: %s", i + 1, len(segments), exc)

        if not partials:
            # All segments failed — fall back to single-pass on the first window
            logger.warning("All segments failed; falling back to single-pass")
            prompt = self._build_extraction_prompt(text[:_SINGLE_PASS_LIMIT], ontology, doc_type)
            raw = self._call_chat_completion(prompt)
            return self._normalize_result(raw, doc_type)

        return self._merge_extractions(partials)

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

        return ExtractedKnowledge(
            summary=final_summary,
            tags=merged_tags,
            entities=merged_entities,
            relations=merged_relations,
            key_points=merged_kp,
            confidence=min(r.confidence for r in results),
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
            result = self._call_chat_completion(prompt)
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
    
    def _normalize_result(self, result: dict, doc_type: str) -> ExtractedKnowledge:
        """Normalize, validate, and quality-filter the raw LLM extraction result."""
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        # Ensure every entity has a stable ID
        for entity in entities:
            if "id" not in entity or not entity["id"]:
                label = entity.get("label", "unknown")
                etype = entity.get("type", "Concept")
                entity["id"] = f"{etype.lower()}_{label.lower().replace(' ', '_')}"

        # ⑤ Quality filter: drop entities below confidence threshold
        entities = [
            e for e in entities
            if float(e.get("confidence", 1.0)) >= MIN_ENTITY_CONFIDENCE
        ]

        # ⑤ Quality filter: drop relations whose endpoints were removed
        entity_ids = {e["id"] for e in entities}
        valid_relations = [
            rel for rel in relations
            if rel.get("source", "") in entity_ids and rel.get("target", "") in entity_ids
        ]

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
