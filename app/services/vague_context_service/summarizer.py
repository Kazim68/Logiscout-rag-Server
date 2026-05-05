"""
Vague context summarizer.

Updates a project's long-term vague_context by folding in:
1. The rolling chat_summary for the session that just produced activity.
2. The latest 6–8 raw messages from that session, which may not yet be
   reflected in the chat_summary.

Reuses the shared Gemini → Groq fallback `LLMClient` and the shared
`ResponsePipelineConfig` so we have a single source of truth for LLM
configuration across the app.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.prompts import VAGUE_CONTEXT_SYSTEM_PROMPT, VAGUE_CONTEXT_USER_PROMPT_TEMPLATE
from app.services.response_pipeline.config import ResponsePipelineConfig
from app.services.response_pipeline.pipeline_steps import LLMClient, LLMUnavailableError
from app.services.summarization_utils import parse_json_object, stringify

logger = logging.getLogger(__name__)


@dataclass
class VagueContextResult:
    vague_context: str
    provider: str  # "llm" | "unavailable" | "parse_failed"
    raw: Optional[str] = None
    error: Optional[str] = None


class VagueContextSummarizer:
    """Updates a project's vague_context using a chat_summary + recent messages."""

    def __init__(
        self,
        config: Optional[ResponsePipelineConfig] = None,
        llm_client: Optional[LLMClient] = None,
    ):
        self.config = config or ResponsePipelineConfig.from_env()
        self.llm = llm_client or LLMClient(self.config)

    async def summarize(
        self,
        *,
        project_id: str,
        chat_summary: Any,
        recent_messages: Any,
        current_vague_context: Any,
    ) -> VagueContextResult:
        system_prompt = VAGUE_CONTEXT_SYSTEM_PROMPT
        user_prompt = VAGUE_CONTEXT_USER_PROMPT_TEMPLATE.format(
            current_vague_context=stringify(current_vague_context),
            chat_summary=stringify(chat_summary),
            recent_messages=stringify(recent_messages),
        )

        logger.info(
            "VagueContext start — project=%s, current_len=%d, summary_len=%d, recent_len=%d",
            project_id,
            len(stringify(current_vague_context)),
            len(stringify(chat_summary)),
            len(stringify(recent_messages)),
        )

        try:
            raw = await self.llm.complete_with_fallback(system_prompt, user_prompt)
        except LLMUnavailableError as exc:
            logger.error("VagueContext failed — LLM unavailable: %s", exc)
            return VagueContextResult(
                vague_context=stringify(current_vague_context) if current_vague_context else "",
                provider="unavailable",
                error="LLM service not available — please try again later.",
            )

        parsed = parse_json_object(raw)
        if parsed is not None and "vague_context" in parsed:
            value = parsed.get("vague_context")
            if not isinstance(value, str):
                value = stringify(value)
            return VagueContextResult(
                vague_context=value.strip(),
                provider="llm",
                raw=raw,
            )

        logger.warning("VagueContext: LLM did not return parseable JSON; using raw text.")
        text = (raw or "").strip()
        return VagueContextResult(
            vague_context=text,
            provider="parse_failed" if text else "unavailable",
            raw=raw,
            error=None if text else "LLM returned an empty response.",
        )
