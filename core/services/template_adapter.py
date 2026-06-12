"""Hyper-Extract template adapter.

Converts Hyper-Extract YAML preset templates into the knowledge_nexus ontology
format (concepts / relations / instructions) consumed by KnowledgeExtractor and
KGraphContextBuilder.

Pipeline position:
    SemanticTemplateMatcher
      -> HyperExtractTemplateAdapter.adapt_by_id()  (Top-K templates)
      -> OntologyResult  {ontology, template_meta, is_native_fallback}
      -> KnowledgeExtractor / KGraphContextBuilder
"""
from __future__ import annotations

import logging
import re
import hashlib
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


#: Hyper-Extract graph-family types — all share the entities/relations output structure.
_GRAPH_TYPES: frozenset[str] = frozenset({
    "graph", "hypergraph", "temporal_graph", "spatial_graph", "spatio_temporal_graph"
})

#: Flat record types — output.fields is a flat list; no entities/relations sub-blocks.
_FLAT_TYPES: frozenset[str] = frozenset({"model", "list", "set"})

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TemplateRecord:
    """Indexed metadata for one bundled Hyper-Extract template."""

    template_id: str
    path: Path
    relative_path: str
    template_hash: str
    name: str
    template_type: str
    tags: list[str]
    language: list[str]
    description: str
    identifiers: dict[str, Any]


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

class TemplateRegistry:
    """Discover and index bundled Hyper-Extract YAML templates."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._dir = templates_dir or TEMPLATES_DIR
        self._records: dict[str, TemplateRecord] | None = None

    def list(
        self,
        *,
        filter_by_type: str | None = None,
        filter_by_tag: str | None = None,
        filter_by_language: str | None = None,
    ) -> list[TemplateRecord]:
        """Return discovered templates, optionally filtered by common metadata."""
        records = list(self._scan().values())
        if filter_by_type is not None:
            records = [record for record in records if record.template_type == filter_by_type]
        if filter_by_tag is not None:
            records = [record for record in records if filter_by_tag in record.tags]
        if filter_by_language is not None:
            records = [record for record in records if filter_by_language in record.language]
        return sorted(records, key=lambda record: record.template_id)

    def get(self, template_id: str) -> TemplateRecord | None:
        """Return one template record by id such as ``general/base_graph``."""
        return self._scan().get(template_id)

    def load(self, template_id: str) -> dict[str, Any] | None:
        """Load the YAML config for one indexed template."""
        record = self.get(template_id)
        if record is None:
            return None
        return self._load_yaml(record.path)

    def _scan(self) -> dict[str, TemplateRecord]:
        if self._records is not None:
            return self._records

        records: dict[str, TemplateRecord] = {}
        if not self._dir.exists():
            self._records = records
            return records

        for path in sorted(self._dir.rglob("*.yaml")):
            raw = self._load_yaml(path)
            if not isinstance(raw, dict):
                continue
            relative_path = path.relative_to(self._dir).as_posix()
            template_id = str(Path(relative_path).with_suffix("")).replace("\\", "/")
            records[template_id] = TemplateRecord(
                template_id=template_id,
                path=path,
                relative_path=relative_path,
                template_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                name=str(raw.get("name", "")),
                template_type=str(raw.get("type", "graph")),
                tags=list(raw.get("tags", [])),
                language=list(raw.get("language", [])),
                description=HyperExtractTemplateAdapter._en(raw.get("description", {})),
                identifiers=dict(raw.get("identifiers", {})),
            )

        self._records = records
        return records

    def _load_yaml(self, path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                return yaml.safe_load(fh)
        except Exception as exc:
            logger.warning("Failed to load template %s: %s", path, exc)
            return None


class HyperExtractTemplateAdapter:
    """Load and adapt a Hyper-Extract YAML preset to knowledge_nexus ontology format."""

    def __init__(self, templates_dir: Path | None = None, registry: TemplateRegistry | None = None) -> None:
        self._dir = templates_dir or TEMPLATES_DIR
        self._registry = registry or TemplateRegistry(self._dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adapt(self, doc_type: str) -> OntologyResult | None:
        """Return :class:`OntologyResult` for the generic ``general/base_graph`` fallback.

        .. deprecated::
            ``adapt(doc_type)`` no longer uses a static doc_type→template map.
            Prefer :meth:`adapt_by_id` or :class:`SemanticTemplateMatcher` for
            proper template selection.  This method exists only as a last-resort
            fallback when no embedding service is configured.
        """
        return self.adapt_by_id("general/base_graph")

    def adapt_by_id(self, template_id: str) -> OntologyResult | None:
        """Return :class:`OntologyResult` for any template by registry ID.

        Supports all Hyper-Extract template types:

        * **graph-family** (``graph``, ``hypergraph``, ``temporal_graph``,
          ``spatial_graph``, ``spatio_temporal_graph``) — converted via
          ``output.entities`` / ``output.relations``.
        * **flat-record** (``model``, ``list``, ``set``) — flat ``output.fields``
          become concepts; a generic ``RELATES_TO`` relation is added so the
          extractor prompt always has at least one relation hint.


        Args:
            template_id: Registry-style identifier such as ``"finance/earnings_summary"``.

        Returns:
            :class:`OntologyResult` with ``is_native_fallback=False``, or
            ``None`` if the template YAML cannot be found on disk.
        """
        record = self._registry.get(template_id)
        if record is None:
            logger.debug("Template not found: %s", template_id)
            return None

        raw = self._registry.load(template_id)
        if raw is None:
            return None

        meta = self._extract_meta(raw, record)
        ontology = self._build_ontology(raw)
        logger.debug(
            "Adapted template '%s' (type=%s) → %d concepts, %d relations",
            template_id,
            raw.get("type", "graph"),
            len(ontology.get("concepts", [])),
            len(ontology.get("relations", [])),
        )
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

    def _extract_meta(self, raw: dict, record: TemplateRecord | None = None) -> dict[str, Any]:
        tracking = {}
        if record is not None:
            tracking = {
                "template_id": record.template_id,
                "relative_path": record.relative_path,
                "template_hash": record.template_hash,
            }
        return {
            **tracking,
            "name": raw.get("name", ""),
            "type": raw.get("type", "graph"),
            "tags": raw.get("tags", []),
            "identifiers": raw.get("identifiers", {}),
            "description": self._en(raw.get("description", {})),
        }

    def _build_ontology(self, raw: dict) -> dict[str, Any]:
        """Convert a Hyper-Extract YAML to ``{concepts, relations, instructions}``.

        Dispatch rules:
        - ``type`` in ``_FLAT_TYPES`` (model/list/set) → flat-field conversion.
        - Everything else (graph-family, unknown) → entities/relations blocks.
        """
        output = raw.get("output", {})
        guideline = raw.get("guideline", {})
        graph_type: str = raw.get("type", "graph")

        if graph_type in _FLAT_TYPES:
            return {
                "concepts": self._parse_flat_concepts(output),
                "relations": [{
                    "relation": "RELATES_TO",
                    "source": "Entity",
                    "target": "Entity",
                    "description": "General semantic relationship between entities",
                }],
                "instructions": self._build_instructions(guideline),
            }

        # graph-family (graph, hypergraph, temporal_graph, spatial_graph,
        # spatio_temporal_graph) and any future graph-like types
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

    def _parse_flat_concepts(self, output: dict) -> list[dict[str, str]]:
        """Convert flat ``output.fields`` (model/list/set templates) to concepts.

        Each field whose name is not a structural meta-field becomes a concept
        type.  The field's English description is used as the concept description.
        """
        fields: list[dict] = output.get("fields", [])
        # Skip purely structural / display fields shared across all flat templates
        skip = {"name", "description", "display_label"}
        concepts: list[dict[str, str]] = []
        for f in fields:
            fname = f.get("name", "")
            if not fname or fname in skip:
                continue
            desc = self._en(f.get("description", {}))
            label = fname.replace("_", " ").title().replace(" ", "")
            concepts.append({"type": label, "description": desc or f"{label} entity."})
        return concepts or [{"type": "Entity", "description": "A named entity in the document."}]

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
