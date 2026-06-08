"""Hyper-Extract template adapter.

Converts Hyper-Extract YAML preset templates into the knowledge_nexus ontology
format (concepts / relations / instructions) consumed by KnowledgeExtractor and
KGraphContextBuilder.

Pipeline position:
    DocumentClassifier
      -> TemplateSelector (via TEMPLATE_MAP)
      -> HyperExtractTemplateAdapter.adapt()
      -> OntologyResult  {ontology, template_meta, is_native_fallback}
      -> KnowledgeExtractor / KGraphContextBuilder
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template locations
# ---------------------------------------------------------------------------

#: Root directory for bundled Hyper-Extract YAML presets.
TEMPLATES_DIR: Path = Path(__file__).parent.parent.parent / "data" / "ontology" / "templates"

#: Mapping from knowledge_nexus doc_type → relative template path (no .yaml suffix).
TEMPLATE_MAP: dict[str, str] = {
    "academic_paper":  "general/concept_graph",      # type: graph ✓ — concept hierarchy
    # technical_doc uses base_graph (general entity types: technology/service/organization)
    # rather than doc_structure (chapter/section focus) so relevance scoring stays sharp
    # on component/API content.  doc_structure is reserved for document-navigation tasks.
    "technical_doc":   "general/base_graph",         # type: graph ✓
    "meeting_minutes": "general/workflow_graph",     # type: temporal_graph → metadata-only
    "report":          "general/base_graph",         # type: graph ✓
    "contract":        "legal/contract_obligation",  # type: hypergraph → metadata-only
    "email":           "general/base_graph",         # type: graph ✓
    "general":         "general/base_graph",         # type: graph ✓
}

#: Only these Hyper-Extract graph types produce a fully-adapted ontology.
_GRAPH_TYPES: frozenset[str] = frozenset({"graph"})

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class OntologyResult:
    """Outcome of adapting one Hyper-Extract template.

    Attributes:
        ontology:           ``{concepts, relations, instructions}`` dict ready
                            for KnowledgeExtractor / KGraphContextBuilder.
                            Empty when *is_native_fallback* is True.
        template_meta:      Raw template metadata (name, type, tags, identifiers,
                            description) for traceability / cross-doc tracking.
        is_native_fallback: True → template type is not ``graph`` (e.g. hypergraph,
                            temporal_graph); caller should use DOCUMENT_TEMPLATES.
    """
    ontology: dict[str, Any] = field(default_factory=dict)
    template_meta: dict[str, Any] = field(default_factory=dict)
    is_native_fallback: bool = False

# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class HyperExtractTemplateAdapter:
    """Load and adapt a Hyper-Extract YAML preset to knowledge_nexus ontology format."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._dir = templates_dir or TEMPLATES_DIR

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adapt(self, doc_type: str) -> OntologyResult | None:
        """Return :class:`OntologyResult` for *doc_type*, or ``None`` if no
        template is mapped / found on disk."""
        rel_path = TEMPLATE_MAP.get(doc_type)
        if rel_path is None:
            return None

        yaml_path = self._dir / f"{rel_path}.yaml"
        raw = self._load_yaml(yaml_path)
        if raw is None:
            return None

        meta = self._extract_meta(raw)
        graph_type: str = raw.get("type", "graph")

        if graph_type not in _GRAPH_TYPES:
            logger.debug(
                "Template '%s' has type=%s — metadata-only (no ontology adaptation)",
                rel_path, graph_type,
            )
            return OntologyResult(template_meta=meta, is_native_fallback=True)

        ontology = self._build_ontology(raw)
        logger.debug("Adapted template '%s' → %d concepts, %d relations",
                     rel_path,
                     len(ontology.get("concepts", [])),
                     len(ontology.get("relations", [])))
        return OntologyResult(ontology=ontology, template_meta=meta, is_native_fallback=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_yaml(self, path: Path) -> dict | None:
        if not path.exists():
            logger.debug("Template YAML not found: %s", path)
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                return yaml.safe_load(fh)
        except Exception as exc:
            logger.warning("Failed to load template %s: %s", path, exc)
            return None

    def _extract_meta(self, raw: dict) -> dict[str, Any]:
        return {
            "name": raw.get("name", ""),
            "type": raw.get("type", "graph"),
            "tags": raw.get("tags", []),
            "identifiers": raw.get("identifiers", {}),
            "description": self._en(raw.get("description", {})),
        }

    def _build_ontology(self, raw: dict) -> dict[str, Any]:
        output = raw.get("output", {})
        guideline = raw.get("guideline", {})
        return {
            "concepts":     self._parse_concepts(output.get("entities", {})),
            "relations":    self._parse_relations(output.get("relations", {})),
            "instructions": self._build_instructions(guideline),
        }

    def _parse_concepts(self, entities_block: dict) -> list[dict[str, str]]:
        fields: list[dict] = entities_block.get("fields", [])
        concepts: list[dict[str, str]] = []

        type_field = next((f for f in fields if f.get("name") == "type"), None)
        if type_field:
            desc_en = self._en(type_field.get("description", {}))
            for example in self._extract_examples(desc_en):
                label = example.replace("_", " ").title().replace(" ", "")
                # Avoid generic stop-words ("the", "from", …) in descriptions so
                # they do not become low-value relevance scoring terms.
                concepts.append({
                    "type": label,
                    "description": f"{label}: named {example.replace('_', ' ')} entity.",
                })

        # Supplement with domain-specific structural fields (level, summary, etc.)
        skip = {"name", "type", "source", "target", "description", "time",
                "reference_context", "condition", "input", "output"}
        for f in fields:
            fname = f.get("name", "")
            if fname in skip:
                continue
            desc = self._en(f.get("description", {}))
            if desc:
                label = fname.replace("_", " ").title().replace(" ", "")
                concepts.append({"type": label, "description": desc})

        return concepts or [{"type": "Entity", "description": "A named entity in the document."}]

    def _parse_relations(self, relations_block: dict) -> list[dict[str, str]]:
        fields: list[dict] = relations_block.get("fields", [])
        relations: list[dict[str, str]] = []

        type_field = next((f for f in fields if f.get("name") == "type"), None)
        if type_field:
            desc_en = self._en(type_field.get("description", {}))
            for example in self._extract_examples(desc_en):
                rel_name = example.upper().replace("-", "_").replace(" ", "_")
                relations.append({
                    "relation": rel_name,
                    "source": "Entity",
                    "target": "Entity",
                    "description": f"{example.replace('_', ' ')} relationship",
                })

        return relations or [{
            "relation": "RELATES_TO",
            "source": "Entity",
            "target": "Entity",
            "description": "General semantic relationship between entities",
        }]

    def _build_instructions(self, guideline: dict) -> str:
        parts: list[str] = []

        target = self._en(guideline.get("target", {}))
        if target:
            parts.append(f"Role: {target}")

        for key in ("rules_for_entities", "rules_for_relations", "rules"):
            rules = guideline.get(key, {})
            if isinstance(rules, dict):
                rules = rules.get("en", [])
            if isinstance(rules, list) and rules:
                label = key.replace("rules_for_", "").replace("_", " ").capitalize()
                joined = " ".join(f"({i + 1}) {r}" for i, r in enumerate(rules))
                parts.append(f"{label} rules: {joined}")

        return " ".join(parts) if parts else "Extract named, specific entities only."

    # ------------------------------------------------------------------
    # String utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _en(field: Any) -> str:
        """Extract English text from a bilingual dict or plain string."""
        if isinstance(field, str):
            return field
        if isinstance(field, dict):
            return str(field.get("en", field.get("zh", "")))
        return ""

    @staticmethod
    def _extract_examples(description: str) -> list[str]:
        """Parse type examples from descriptions like 'Entity type: X/Y/Z, etc.'"""
        match = re.search(
            r"(?:examples?:\s*|:\s*)([a-z][a-z_/,\s]+?)(?:\s*,?\s*etc\.?|$)",
            description,
            re.IGNORECASE,
        )
        if not match:
            return []
        raw_types = re.split(r"[/,]", match.group(1).strip())
        result: list[str] = []
        skip = {"etc", "and", "or", "the", "e", "g"}
        for t in raw_types:
            t = t.strip().strip(".")
            if t and t.lower() not in skip and len(t) > 1:
                result.append(t.lower())
        return result[:10]
