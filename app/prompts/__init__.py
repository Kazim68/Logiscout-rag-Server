"""Centralized LLM prompts for LogiScout.

All system and user-prompt templates live here so prompt engineering can
happen in one place without touching service code. Each module exposes
the prompts for one logical feature; this package re-exports them.
"""

from .intent import (
    INTENT_SYSTEM_PROMPT,
    INTENT_USER_PROMPT_TEMPLATE,
)
from .answer import (
    ANSWER_SYSTEM_PROMPT,
    ANSWER_USER_PROMPT_TEMPLATE,
)
from .vague_context import (
    VAGUE_CONTEXT_SYSTEM_PROMPT,
    VAGUE_CONTEXT_USER_PROMPT_TEMPLATE,
)
from .chat_summary import (
    CHAT_SUMMARY_SYSTEM_PROMPT,
    CHAT_SUMMARY_USER_PROMPT_TEMPLATE,
)

__all__ = [
    "INTENT_SYSTEM_PROMPT",
    "INTENT_USER_PROMPT_TEMPLATE",
    "ANSWER_SYSTEM_PROMPT",
    "ANSWER_USER_PROMPT_TEMPLATE",
    "VAGUE_CONTEXT_SYSTEM_PROMPT",
    "VAGUE_CONTEXT_USER_PROMPT_TEMPLATE",
    "CHAT_SUMMARY_SYSTEM_PROMPT",
    "CHAT_SUMMARY_USER_PROMPT_TEMPLATE",
]
