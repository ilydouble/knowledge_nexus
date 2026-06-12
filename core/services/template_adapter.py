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

#: Mapping from knowledge_nexus doc_type → relative template path (no .yaml suffix).
#: nexus/ paths use schema: nexus-v1 format; HE paths are general/legal/… subdirs.
TEMPLATE_MAP: dict[str, str] = {
    # Core general doc types
    "academic_paper":  "nexus/academic_paper",
    "technical_doc":   "nexus/technical_doc",
    "meeting_minutes": "nexus/meeting_minutes",
    "report":          "nexus/report",
    "contract":        "nexus/contract",
    "email":           "nexus/email",
    "tabular_data":    "nexus/tabular_data",
    "general":         "nexus/general",
    # Domain-specific doc types
    "financial_report":  "nexus/financial_report",
    "medical_record":    "nexus/medical_record",
    "tcm_text":          "nexus/tcm_text",
    "industry_manual":   "nexus/industry_manual",
    "smart_campus":      "nexus/smart_campus",
    "legal_case":        "nexus/legal_case",
    "biography":         "nexus/biography",
    "workflow_doc":      "nexus/workflow_doc",
}

#: Ordered candidate templates for kgraph input preparation. These are used for
#: traceable template selection metadata, not as a guarantee that the extractor
#: will replace its native ontology.
#: nexus/ paths are listed first (primary ontology source); HE paths follow as hints.
DOC_TYPE_TEMPLATE_HINTS: dict[str, list[str]] = {
    # Core general doc types
    "academic_paper": ["nexus/academic_paper", "general/concept_graph", "general/doc_structure"],
    "technical_doc": [
        "nexus/technical_doc",
        "general/base_graph",
        "general/doc_structure",
        "industry/equipment_topology",
        "industry/operation_flow",
    ],
    "meeting_minutes": ["nexus/meeting_minutes", "general/workflow_graph", "industry/operation_flow"],
    "report": ["nexus/report", "finance/earnings_summary", "finance/event_timeline", "general/base_graph"],
    "contract": [
        "nexus/contract",
        "legal/contract_obligation",
        "legal/defined_term_set",
        "legal/compliance_list",
        "legal/case_fact_timeline",
    ],
    "email": ["nexus/email", "general/base_graph"],
    "tabular_data": ["nexus/tabular_data", "general/base_model", "general/base_list"],
    "general": ["nexus/general", "general/base_graph", "general/concept_graph"],
    # Domain-specific doc types
    "financial_report": [
        "nexus/financial_report",
        "finance/ownership_graph",
        "finance/event_timeline",
        "finance/risk_factor_set",
        "finance/earnings_summary",
    ],
    "medical_record": [
        "nexus/medical_record",
        "medicine/drug_interaction",
        "medicine/hospital_timeline",
        "medicine/anatomy_graph",
        "medicine/treatment_map",
    ],
    "tcm_text": [
        "nexus/tcm_text",
        "tcm/herb_relation",
        "tcm/meridian_graph",
        "tcm/formula_composition",
        "tcm/syndrome_reasoning",
    ],
    "industry_manual": [
        "nexus/industry_manual",
        "industry/equipment_topology",
        "industry/operation_flow",
        "industry/failure_case",
        "industry/safety_control",
        "industry/emergency_response",
    ],
    "smart_campus": [
        "nexus/smart_campus",
        "industry/equipment_topology",
        "industry/failure_case",
        "industry/safety_control",
        "industry/emergency_response",
        "general/base_spatio_temporal_graph",
    ],
    "legal_case": [
        "nexus/legal_case",
        "legal/case_citation",
        "legal/case_fact_timeline",
        "legal/contract_obligation",
        "legal/compliance_list",
    ],
    "biography": [
        "nexus/biography",
        "general/biography_graph",
    ],
    "workflow_doc": [
        "nexus/workflow_doc",
        "general/workflow_graph",
        "industry/operation_flow",
    ],
}

BUSINESS_DOMAIN_TAGS: dict[str, str] = {
    "business": "finance",
    "engineering": "industry",
    "legal": "legal",
    "healthcare": "medicine",
    "medicine": "medicine",
    "tcm": "tcm",
}

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


@dataclass(frozen=True)
class TemplateSelection:
    """Ranked template candidate for one document classification."""

    template_id: str
    name: str
    template_type: str
    tags: list[str]
    relative_path: str
    template_hash: str
    description: str
    identifiers: dict[str, Any]
    score: float
    reason: str
    is_primary: bool
    graph_compatible: bool

    def as_dict(self) -> dict[str, Any]:
        """Serialize selection metadata for the kgraph context JSON contract."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "type": self.template_type,
            "tags": self.tags,
            "relative_path": self.relative_path,
            "template_hash": self.template_hash,
            "description": self.description,
            "identifiers": self.identifiers,
            "score": round(self.score, 3),
            "reason": self.reason,
            "is_primary": self.is_primary,
            "graph_compatible": self.graph_compatible,
        }


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


class TemplateSelector:
    """Select ranked Hyper-Extract template candidates for a classified document."""

    def __init__(self, registry: TemplateRegistry | None = None) -> None:
        self._registry = registry or TemplateRegistry()

    def select(
        self,
        doc_type: str,
        *,
        business_domain: str | None = None,
        max_candidates: int = 5,
    ) -> list[TemplateSelection]:
        """Return ranked template candidates for kgraph input preparation."""
        selected: list[TemplateSelection] = []
        seen: set[str] = set()
        explicit_ids = DOC_TYPE_TEMPLATE_HINTS.get(doc_type)
        reason = "doc_type" if explicit_ids else "fallback"
        candidate_ids = explicit_ids or DOC_TYPE_TEMPLATE_HINTS["general"]

        for index, template_id in enumerate(candidate_ids):
            record = self._registry.get(template_id)
            if record is None:
                continue
            selected.append(self._selection_from_record(record, 1.0 - index * 0.08, reason, not selected))
            seen.add(record.template_id)

        domain_tag = BUSINESS_DOMAIN_TAGS.get(business_domain or "")
        if domain_tag:
            for index, record in enumerate(self._registry.list(filter_by_tag=domain_tag)):
                if record.template_id in seen:
                    continue
                selected.append(
                    self._selection_from_record(
                        record,
                        0.6 - min(index, 4) * 0.03,
                        "business_domain",
                        not selected,
                    )
                )
                seen.add(record.template_id)
                if len(selected) >= max_candidates:
                    break

        return selected[:max_candidates]

    def _selection_from_record(
        self,
        record: TemplateRecord,
        score: float,
        reason: str,
        is_primary: bool,
    ) -> TemplateSelection:
        return TemplateSelection(
            template_id=record.template_id,
            name=record.name,
            template_type=record.template_type,
            tags=record.tags,
            relative_path=record.relative_path,
            template_hash=record.template_hash,
            description=record.description,
            identifiers=record.identifiers,
            score=max(score, 0.0),
            reason=reason,
            is_primary=is_primary,
            graph_compatible=record.template_type in (_GRAPH_TYPES | _FLAT_TYPES),
        )


class HyperExtractTemplateAdapter:
    """Load and adapt a Hyper-Extract YAML preset to knowledge_nexus ontology format."""

    def __init__(self, templates_dir: Path | None = None, registry: TemplateRegistry | None = None) -> None:
        self._dir = templates_dir or TEMPLATES_DIR
        self._registry = registry or TemplateRegistry(self._dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adapt(self, doc_type: str) -> OntologyResult | None:
        """Return :class:`OntologyResult` for *doc_type* via TEMPLATE_MAP, or ``None``."""
        rel_path = TEMPLATE_MAP.get(doc_type)
        if rel_path is None:
            return None
        return self.adapt_by_id(rel_path)

    def adapt_by_id(self, template_id: str) -> OntologyResult | None:
        """Return :class:`OntologyResult` for any template by registry ID.

        Supports all Hyper-Extract template types:

        * **graph-family** (``graph``, ``hypergraph``, ``temporal_graph``,
          ``spatial_graph``, ``spatio_temporal_graph``) — converted via
          ``output.entities`` / ``output.relations``.
        * **flat-record** (``model``, ``list``, ``set``) — flat ``output.fields``
          become concepts; a generic ``RELATES_TO`` relation is added so the
          extractor prompt always has at least one relation hint.
        * **nexus-v1** schema — loaded directly from the YAML's
          ``concepts``/``relations``/``instructions`` keys (legacy; will be
          removed once nexus templates are deleted).

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
        - ``schema: nexus-v1`` → direct load (legacy nexus format).
        - ``type`` in ``_FLAT_TYPES`` (model/list/set) → flat-field conversion.
        - Everything else (graph-family, unknown) → entities/relations blocks.
        """
        if raw.get("schema") == "nexus-v1":
            return self._build_nexus_ontology(raw)

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

    def _build_nexus_ontology(self, raw: dict) -> dict[str, Any]:
        """Directly load concepts/relations/instructions from a nexus-v1 YAML."""
        instructions = raw.get("instructions", "")
        if isinstance(instructions, list):
            instructions = " ".join(instructions)
        return {
            "concepts":     list(raw.get("concepts", [])),
            "relations":    list(raw.get("relations", [])),
            "instructions": str(instructions).strip() or "Extract named, specific entities only.",
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
