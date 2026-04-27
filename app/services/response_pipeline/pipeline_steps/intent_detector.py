"""
Intent detection step — first stage of the response pipeline.

Uses the shared LLMClient (Gemini → Groq fallback chain) to classify
the user's intent and decide which retrieval sources are needed.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .ID_fallback_chain import LLMClient, LLMUnavailableError

logger = logging.getLogger(__name__)


VALID_INTENTS = {
    "incident_investigation",
    "commit_lookup",
    "code_explanation",
    "status_check",
    "general_question",
    "unknown",
}


@dataclass
class IntentResult:
    intent: str
    confidence: float
    rationale: str
    needs_logs: bool
    needs_commits: bool
    needs_postmortem: bool
    provider: str  # "llm" | "unavailable"
    raw: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "needs_logs": self.needs_logs,
            "needs_commits": self.needs_commits,
            "needs_postmortem": self.needs_postmortem,
            "provider": self.provider,
            "error": self.error,
        }


class IntentDetector:
    """Classifies the user's intent using the LLM fallback chain."""

    def __init__(self, config, llm_client: Optional[LLMClient] = None):
        self.config = config
        self.llm = llm_client or LLMClient(config)

    def _build_user_prompt(
        self,
        vague_context: Any,
        chat_context: Any,
        user_prompt: str,
    ) -> str:
        return self.config.intent_user_prompt_template.format(
            vague_context=_stringify(vague_context),
            chat_context=_stringify(chat_context),
            user_prompt=user_prompt,
        )

    async def detect(
        self,
        vague_context: Any,
        chat_context: Any,
        user_prompt: str,
    ) -> IntentResult:
        """
        Run intent detection. Never raises — on full LLM failure, returns
        an IntentResult with provider="unavailable" and an error message.
        """
        system_prompt = self.config.intent_system_prompt
        user_msg = self._build_user_prompt(vague_context, chat_context, user_prompt)

        try:
            raw = await self.llm.complete_with_fallback(system_prompt, user_msg)
        except LLMUnavailableError as e:
            logger.error("Intent detection failed — LLM unavailable: %s", e)
            return IntentResult(
                intent="unknown",
                confidence=0.0,
                rationale="",
                needs_logs=False,
                needs_commits=False,
                needs_postmortem=False,
                provider="unavailable",
                error="LLM service not available — please try again later.",
            )

        parsed = _parse_intent_json(raw)
        if parsed is None:
            logger.warning("Intent JSON parse failed; raw=%r", raw[:300])
            return IntentResult(
                intent="unknown",
                confidence=0.0,
                rationale="LLM returned an unparseable response.",
                needs_logs=False,
                needs_commits=False,
                needs_postmortem=False,
                provider="llm",
                raw=raw,
            )

        intent = str(parsed.get("intent", "unknown")).strip()
        if intent not in VALID_INTENTS:
            logger.warning("Intent value %r not in known set; coercing to 'unknown'", intent)
            intent = "unknown"

        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        rationale = str(parsed.get("rationale", "")).strip()

        return IntentResult(
            intent=intent,
            confidence=confidence,
            rationale=rationale,
            needs_logs=_coerce_bool(parsed.get("needs_logs")),
            needs_commits=_coerce_bool(parsed.get("needs_commits")),
            needs_postmortem=_coerce_bool(parsed.get("needs_postmortem")),
            provider="llm",
            raw=raw,
        )


# ── Helpers ──────────────────────────────────────────────────────────


def _stringify(value: Any) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return value if value.strip() else "(none)"
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_intent_json(raw: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from the LLM response, tolerating code fences."""
    if not raw:
        return None

    text = raw.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
