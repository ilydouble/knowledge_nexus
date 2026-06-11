"""Shared model factory — builds a Strands OpenAIModel from nexus Settings."""

from __future__ import annotations

from strands.models.openai import OpenAIModel

from core.settings import Settings


def build_model(settings: Settings | None = None) -> OpenAIModel:
    """Return an OpenAIModel compatible with ZhipuAI (OpenAI-compat API).

    The settings ``llm_base_url`` typically ends with ``/chat/completions``;
    the OpenAI SDK expects the root base URL without that suffix.
    """
    cfg = settings or Settings.from_env()

    base_url = cfg.llm_base_url
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]
    if not base_url.endswith("/"):
        base_url += "/"

    api_key = cfg.zhipu_api_key or cfg.openai_api_key or "no-key"

    return OpenAIModel(
        model_id=cfg.llm_model,
        api_key=api_key,
        base_url=base_url,
        params={"temperature": 0.1, "max_tokens": 1024},
    )
