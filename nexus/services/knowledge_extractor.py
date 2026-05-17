"""Knowledge Extractor - Extract structured knowledge from text using LLM."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from nexus.settings import Settings

logger = logging.getLogger(__name__)


# Path to knowledge-graph skill
SKILL_PATH = Path(__file__).parent.parent.parent / "knowledge-graph"


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


# Default ontology for general documents
DEFAULT_ONTOLOGY = {
    "concepts": [
        {"type": "Person", "description": "A human being, named individual"},
        {"type": "Organization", "description": "A group or company"},
        {"type": "Project", "description": "A project or initiative"},
        {"type": "Technology", "description": "A technology, tool, or framework"},
        {"type": "Concept", "description": "An abstract idea or topic"},
        {"type": "Location", "description": "A geographical place"},
        {"type": "Event", "description": "An occurrence in time"},
        {"type": "Metric", "description": "A measurement or KPI"},
        {"type": "Document", "description": "A document or file"},
    ],
    "relations": [
        {"relation": "WORKS_AT", "source": "Person", "target": "Organization"},
        {"relation": "WORKS_ON", "source": "Person", "target": "Project"},
        {"relation": "USES", "source": "Person", "target": "Technology"},
        {"relation": "DEVELOPS", "source": "Organization", "target": "Technology"},
        {"relation": "PART_OF", "source": "Entity", "target": "Entity"},
        {"relation": "DEPENDS_ON", "source": "Entity", "target": "Entity"},
        {"relation": "RELATES_TO", "source": "Entity", "target": "Entity"},
        {"relation": "LOCATED_IN", "source": "Entity", "target": "Location"},
        {"relation": "MEASURES", "source": "Metric", "target": "Entity"},
    ],
}

# Document type specific templates
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

DOCUMENT_TEMPLATES = {
    "academic_paper": {
        "entity_types": ["Researcher", "Institution", "Method", "Dataset", "Metric", "Concept"],
        "relation_types": ["AUTHORED_BY", "USES_METHOD", "ACHIEVES_METRIC", "CITES", "ADDRESSES"],
        "extraction_focus": "research_question, methodology, experiments, conclusions, contributions",
    },
    "technical_doc": {
        "entity_types": ["Component", "API", "Database", "Framework", "Service", "Config"],
        "relation_types": ["DEPENDS_ON", "CALLS", "STORES_IN", "IMPLEMENTS", "CONFIGURES"],
        "extraction_focus": "architecture, components, interfaces, dependencies",
    },
    "meeting_minutes": {
        "entity_types": ["Person", "Task", "Decision", "Project", "Deadline"],
        "relation_types": ["ASSIGNED_TO", "DECIDED_BY", "RELATES_TO", "DUE_BY"],
        "extraction_focus": "decisions, action_items, participants, deadlines",
    },
    "report": {
        "entity_types": ["Metric", "Project", "Team", "Risk", "Milestone", "Status"],
        "relation_types": ["REPORTS_ON", "HAS_RISK", "ACHIEVED_BY", "STATUS_OF"],
        "extraction_focus": "key_metrics, progress, risks, recommendations",
    },
}


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
    ) -> ExtractedKnowledge:
        """Extract knowledge from text, using map-reduce for long documents.

        For documents shorter than ``_MAP_REDUCE_THRESHOLD`` a single LLM call
        is made (same as before).  For longer documents the text is split into
        overlapping segments and each segment is extracted independently; the
        results are then merged and deduplicated.

        Args:
            text: The text content to extract knowledge from.
            doc_type: Type of document (academic_paper, technical_doc, etc.)
            ontology: Custom ontology (uses default if not provided).

        Returns:
            ExtractedKnowledge with entities, relations, and summary.
        """
        if not self.api_key:
            return self._mock_extraction(text, doc_type)

        if ontology is None:
            ontology = self._get_ontology(doc_type)

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
        """Get ontology for document type."""
        # Try to use knowledge-graph skill's ontology builder
        try:
            result = subprocess.run(
                ["python", str(SKILL_PATH / "scripts" / "ontology_builder.py"),
                 "--action", "suggest", "--domain", doc_type],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                ontology_data = json.loads(result.stdout)
                return {
                    "concepts": ontology_data.get("suggested_concepts", []) + ontology_data.get("base_concepts", []),
                    "relations": ontology_data.get("base_relations", []),
                }
        except Exception:
            pass
        
        # Use default or template-specific ontology
        if doc_type in DOCUMENT_TEMPLATES:
            template = DOCUMENT_TEMPLATES[doc_type]
            return {
                "concepts": [{"type": t, "description": f"{t} entity"} for t in template["entity_types"]],
                "relations": [{"relation": r, "source": "Entity", "target": "Entity"} for r in template["relation_types"]],
            }
        
        return DEFAULT_ONTOLOGY
    
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
        """Build the extraction prompt."""
        concept_types = [c["type"] for c in ontology.get("concepts", [])]
        relation_types = [r["relation"] for r in ontology.get("relations", [])]
        
        template_info = ""
        if doc_type in DOCUMENT_TEMPLATES:
            template_info = f"\nDocument Type: {doc_type}\nFocus on: {DOCUMENT_TEMPLATES[doc_type].get('extraction_focus', 'general content')}"
        
        return f"""Analyze the following document and extract structured knowledge.

{template_info}

## Ontology
Entity Types: {', '.join(concept_types)}
Relation Types: {', '.join(relation_types)}

## Output Format
Return a JSON object with this exact structure:
{{
  "summary": "Brief summary of the document (2-3 sentences)",
  "tags": ["tag1", "tag2", "tag3"],
  "entities": [
    {{
      "id": "unique_id",
      "label": "Display Name",
      "type": "EntityType",
      "description": "Brief description"
    }}
  ],
  "relations": [
    {{
      "source": "entity_id",
      "target": "entity_id",
      "relation": "RELATION_TYPE",
      "evidence": "Quote from text supporting this relation"
    }}
  ],
  "key_points": [
    {{
      "content": "Key insight or fact",
      "type": "conclusion|recommendation|data",
      "confidence": 0.9
    }}
  ]
}}

## Rules
1. Use entity types from the ontology. For unknown types, use "Concept".
2. Generate stable IDs: lowercase(type) + "_" + lowercase(label).replace(" ", "_")
3. Only create relations that are clearly stated or strongly implied in the text.
4. Include evidence for relations when possible.
5. Set confidence 0.8+ only when fairly certain.

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
