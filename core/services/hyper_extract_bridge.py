"""Optional Hyper-Extract runtime bridge for kgraph candidate generation."""

from __future__ import annotations

import logging
import importlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from core.services.template_adapter import TEMPLATES_DIR

logger = logging.getLogger(__name__)

RuntimeRunner = Callable[[dict[str, Any], str], Any]


def make_template_factory_runner(
    *,
    llm_client: Any,
    embedder: Any,
    template_root: Path | str = TEMPLATES_DIR,
    language: str = "zh",
    **factory_kwargs: Any,
) -> RuntimeRunner:
    """Create a runner backed by Hyper-Extract's TemplateFactory.

    This function imports Hyper-Extract lazily so the core pipeline can run
    without the runtime dependency installed.
    """

    def runner(template: dict[str, Any], text: str) -> Any:
        module = importlib.import_module("hyperextract.utils.template_engine")
        template_factory = module.TemplateFactory
        relative_path = template.get("relative_path")
        if not relative_path:
            raise ValueError("selected template missing relative_path")
        source = Path(template_root) / str(relative_path)
        instance = template_factory.create(
            str(source),
            language,
            llm_client,
            embedder,
            **factory_kwargs,
        )
        return instance.parse(text)

    return runner


class HyperExtractRuntimeBridge:
    """Run selected Hyper-Extract templates as optional candidate generators.

    The bridge is intentionally opt-in. Its output is treated as candidate
    evidence for kgraph, not as final graph state.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        runner: RuntimeRunner | None = None,
        max_templates: int = 1,
    ) -> None:
        self.enabled = enabled
        self.runner = runner
        self.max_templates = max_templates

    def extract_candidates(
        self,
        *,
        text: str,
        selected_templates: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return normalized candidate extractions for selected templates."""
        if not self.enabled:
            return []

        if self.runner is None:
            logger.info("Hyper-Extract runtime bridge enabled without runner; skipping")
            return []

        candidates: list[dict[str, Any]] = []
        for template in list(selected_templates)[: self.max_templates]:
            try:
                raw = self.runner(template, text)
                candidates.append(self._success_candidate(template, raw))
            except Exception as exc:  # pragma: no cover - exact exception types are runtime-specific
                logger.warning(
                    "Hyper-Extract candidate generation failed for template %s: %s",
                    template.get("template_id"),
                    exc,
                )
                candidates.append(self._error_candidate(template, exc))
        return candidates

    def _success_candidate(self, template: dict[str, Any], raw: Any) -> dict[str, Any]:
        normalized = self._normalize_raw(raw)
        return {
            "template_id": template.get("template_id"),
            "template_hash": template.get("template_hash"),
            "template_type": template.get("type"),
            "status": "success",
            "candidate_entities": normalized["entities"],
            "candidate_relations": normalized["relations"],
            "candidate_items": normalized["items"],
            "raw": normalized["raw"],
        }

    def _error_candidate(self, template: dict[str, Any], exc: Exception) -> dict[str, Any]:
        return {
            "template_id": template.get("template_id"),
            "template_hash": template.get("template_hash"),
            "template_type": template.get("type"),
            "status": "error",
            "candidate_entities": [],
            "candidate_relations": [],
            "candidate_items": [],
            "raw": {},
            "error": str(exc),
        }

    def _normalize_raw(self, raw: Any) -> dict[str, Any]:
        payload = self._to_plain(raw)
        if isinstance(payload, dict):
            entities = payload.get("nodes") or payload.get("entities") or []
            relations = payload.get("edges") or payload.get("relations") or payload.get("hyperedges") or []
            items = payload.get("items") or payload.get("data") or []
        elif isinstance(payload, list):
            entities = []
            relations = []
            items = payload
        else:
            entities = []
            relations = []
            items = []

        return {
            "entities": self._ensure_list(entities),
            "relations": self._ensure_list(relations),
            "items": self._ensure_list(items),
            "raw": payload if isinstance(payload, dict | list) else {"value": payload},
        }

    def _to_plain(self, raw: Any) -> Any:
        if hasattr(raw, "model_dump"):
            return raw.model_dump()
        if hasattr(raw, "dict"):
            return raw.dict()
        if hasattr(raw, "data"):
            return self._to_plain(raw.data)
        return raw

    def _ensure_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]
