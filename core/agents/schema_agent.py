"""Agent2 — Schema Discovery Agent.

Triggered when a document is classified as 'general' and the system
suspects it may belong to a new domain not yet covered by existing templates.
Proposes a new nexus-v1 YAML schema that can be reviewed and persisted.
"""

from __future__ import annotations

import json
import logging

from strands import Agent, tool

from core.agents._model import build_model
from core.services.template_adapter import TemplateRegistry
from core.settings import Settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an ontology designer for a knowledge graph extraction system.
Given a document, propose a nexus-v1 schema (YAML format) that captures
the key entities and relationships in that domain.

Steps:
1. Call list_nexus_schemas() to understand existing schema patterns.
2. Call get_schema_example(doc_type) to study a representative schema.
3. Analyze the document content and propose a new schema.

Output a YAML block in this exact format (no markdown fences):
schema: nexus-v1
name: <schema name>
type: graph
description: <one-line description>
concepts:
  - <EntityType1>
  - <EntityType2>
relations:
  - name: <relation_name>
    from: <EntityType1>
    to: <EntityType2>
    description: <what this relation means>
instructions: |
  Extract <EntityType1> nodes for ...
  Extract <EntityType2> nodes for ...
  Build <relation_name> edges when ...
  Do NOT extract generic nouns as entities.
"""


def create_schema_agent(settings: Settings | None = None) -> Agent:
    """Return a configured Strands Agent for schema discovery."""
    registry = TemplateRegistry()
    model = build_model(settings)

    @tool
    def list_nexus_schemas() -> str:
        """List all existing nexus-v1 native schemas (id + description)."""
        nexus_records = [r for r in registry.list() if r.template_id.startswith("nexus/")]
        return json.dumps(
            [{"id": r.template_id, "name": r.name, "description": r.description} for r in nexus_records],
            ensure_ascii=False,
        )

    @tool
    def get_schema_example(doc_type: str) -> str:
        """Return the full YAML content of an existing nexus schema as reference.

        Args:
            doc_type: A doc_type like 'financial_report', 'medical_record', 'contract'.
        """
        raw = registry.load(f"nexus/{doc_type}")
        if raw is None:
            raw = registry.load(doc_type)
        if raw is None:
            return json.dumps({"error": f"Schema for '{doc_type}' not found"})
        import yaml
        return yaml.dump(raw, allow_unicode=True, default_flow_style=False)

    return Agent(
        model=model,
        tools=[list_nexus_schemas, get_schema_example],
        system_prompt=_SYSTEM_PROMPT,
    )


def discover_schema(
    filename: str,
    content_preview: str,
    agent: Agent,
) -> str:
    """Run the schema agent and return proposed YAML string.

    Returns an empty string on failure.
    """
    prompt = (
        f"Propose a new nexus-v1 schema for this document.\n"
        f"Filename: {filename}\n"
        f"Content preview (first 800 chars):\n{content_preview[:800]}"
    )
    try:
        result = agent(prompt)
        return str(result).strip()
    except Exception as exc:
        logger.warning("Schema discovery agent failed: %s", exc)
        return ""
