"""
Chat session summarizer.

Takes the rolling summary of one chat session plus the latest batch of
new messages (typically 10) and asks the LLM to produce an updated
rolling summary. Reuses the shared LLM fallback chain and config.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.prompts import CHAT_SUMMARY_SYSTEM_PROMPT, CHAT_SUMMARY_USER_PROMPT_TEMPLATE
from app.services.response_pipeline.config import ResponsePipelineConfig
from app.services.response_pipeline.pipeline_steps import LLMClient, LLMUnavailableError
from app.services.summarization_utils import parse_json_object, stringify

logger = logging.getLogger(__name__)


@dataclass
class ChatSummaryResult:
    chat_summary: str
    provider: str  # "llm" | "unavailable" | "parse_failed"
    raw: Optional[str] = None
    error: Optional[str] = None


class ChatSummarizer:
    """Updates a chat session's rolling summary by folding in new messages."""

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
        chat_id: str,
        previous_summary: Any,
        new_messages: Any,
    ) -> ChatSummaryResult:
        system_prompt = CHAT_SUMMARY_SYSTEM_PROMPT
        user_prompt = CHAT_SUMMARY_USER_PROMPT_TEMPLATE.format(
            project_id=project_id,
            chat_id=chat_id,
            previous_summary=stringify(previous_summary),
            new_messages=stringify(new_messages),
        )

        logger.info(
            "ChatSummary start — project=%s, chat=%s, prev_len=%d, new_len=%d",
            project_id,
            chat_id,
            len(stringify(previous_summary)),
            len(stringify(new_messages)),
        )

        try:
            raw = await self.llm.complete_with_fallback(system_prompt, user_prompt)
        except LLMUnavailableError as exc:
            logger.error("ChatSummary failed — LLM unavailable: %s", exc)
            return ChatSummaryResult(
                chat_summary=stringify(previous_summary) if previous_summary else "",
                provider="unavailable",
                error="LLM service not available — please try again later.",
            )

        parsed = parse_json_object(raw)
        if parsed is not None and "chat_summary" in parsed:
            value = parsed.get("chat_summary")
            if not isinstance(value, str):
                value = stringify(value)
            return ChatSummaryResult(
                chat_summary=value.strip(),
                provider="llm",
                raw=raw,
            )

        logger.warning("ChatSummary: LLM did not return parseable JSON; using raw text.")
        text = (raw or "").strip()
        return ChatSummaryResult(
            chat_summary=text,
            provider="parse_failed" if text else "unavailable",
            raw=raw,
            error=None if text else "LLM returned an empty response.",
        )
