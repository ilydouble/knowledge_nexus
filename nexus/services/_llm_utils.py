"""Shared helpers for parsing JSON-ish LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from a response that may include prose or fences."""
    if not text or not text.strip():
        return None

    candidate = text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"```(?:json)?\s*\n?(.*?)\n?\s*```", candidate, re.DOTALL):
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue

    start = candidate.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(candidate)):
        char = candidate[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[start : index + 1])
                except json.JSONDecodeError:
                    return None

    return None
