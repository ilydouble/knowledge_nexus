"""Agent1 — Template Classifier Agent.

Triggered when keyword-based classification confidence < 0.4.
Uses the template registry and doc-type catalogue as tools so the LLM can
reason its way to the right doc_type without exhausting the context window.
"""

from __future__ import annotations

import json
import logging

from strands import Agent, tool

from nexus.agents._model import build_model
from nexus.services.template_adapter import TemplateRegistry
from nexus.settings import Settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a document classification expert for a knowledge graph system.
Your task: given a document filename and a short content preview, identify
the most appropriate doc_type from the available categories.

Steps:
1. Call list_doc_types() to see all available categories.
2. If unsure, call search_templates(query) with domain keywords from the document.
3. Optionally call get_template_detail(template_id) to inspect concepts.
4. Output ONLY a JSON object: {"doc_type": "<chosen_type>", "reason": "<1 sentence>"}

Rules:
- Choose exactly one doc_type from the listed categories.
- Prefer the most specific match over "general".
- Output valid JSON with no markdown fences.
"""


def create_classifier_agent(settings: Settings | None = None) -> Agent:
    """Return a configured Strands Agent for document type classification."""
    registry = TemplateRegistry()
    model = build_model(settings)

    @tool
    def list_doc_types() -> str:
        """List all available document type categories with their descriptions."""
        from nexus.services.document_classifier import CATEGORIES  # avoid circular at module level
        return json.dumps(
            [{"doc_type": k, "description": v["description"]} for k, v in CATEGORIES.items()],
            ensure_ascii=False,
        )

    @tool
    def search_templates(query: str) -> str:
        """Search templates by keyword. Returns id, name and description of matches.

        Args:
            query: Domain keyword(s) to search for (e.g. 'finance', 'medical record').
        """
        q = query.lower()
        matches = [
            r for r in registry.list()
            if q in r.name.lower() or q in r.description.lower() or any(q in t.lower() for t in r.tags)
        ]
        return json.dumps(
            [{"id": r.template_id, "name": r.name, "description": r.description} for r in matches[:12]],
            ensure_ascii=False,
        )

    @tool
    def get_template_detail(template_id: str) -> str:
        """Get concepts and relations for a specific template.

        Args:
            template_id: Template identifier such as 'nexus/financial_report'.
        """
        raw = registry.load(template_id)
        if raw is None:
            return json.dumps({"error": f"Template '{template_id}' not found"})
        return json.dumps(
            {
                "id": template_id,
                "description": raw.get("description", ""),
                "concepts": raw.get("concepts", []),
                "relations": [r.get("name", r) if isinstance(r, dict) else r for r in raw.get("relations", [])],
            },
            ensure_ascii=False,
        )

    return Agent(
        model=model,
        tools=[list_doc_types, search_templates, get_template_detail],
        system_prompt=_SYSTEM_PROMPT,
    )


def classify_with_agent(
    filename: str,
    content_preview: str,
    agent: Agent,
) -> tuple[str, str]:
    """Run the classifier agent and return (doc_type, reason).

    Falls back to ``("general", "agent fallback")`` on any error.
    """
    prompt = (
        f"Classify this document.\n"
        f"Filename: {filename}\n"
        f"Content preview (first 600 chars):\n{content_preview[:600]}"
    )
    try:
        result = agent(prompt)
        text = str(result).strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        parsed = json.loads(text)
        doc_type = str(parsed.get("doc_type", "general"))
        reason = str(parsed.get("reason", ""))
        return doc_type, reason
    except Exception as exc:
        logger.warning("Classifier agent failed: %s", exc)
        return "general", f"agent error: {exc}"
