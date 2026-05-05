"""Shared helpers for LLM-driven summarization services.

Both vague_context and chat_summary services need to:
1. Stringify arbitrary JSON-ish payloads for use inside a prompt template.
2. Parse a JSON object back out of an LLM response that may include code
   fences, leading/trailing prose, or just be a JSON literal.

Centralizing keeps the parsing tolerant in one place.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def stringify(value: Any) -> str:
    """Render an arbitrary value for safe interpolation into a prompt template."""
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return value if value.strip() else "(none)"
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def parse_json_object(raw: Optional[str]) -> Optional[dict]:
    """Extract a JSON object from an LLM response, tolerating code fences."""
    if not raw:
        return None

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            result = json.loads(match.group(0))
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None
    return None
