"""Centralized configuration for the Response Pipeline.

All environment-derived values are sourced from `app.core.settings.settings`
so the rest of the app has a single source of truth for env vars. Non-env
constants (prompts, model lists, hyperparameters) live here as developer-
configurable defaults.
"""
from dataclasses import dataclass, field
from typing import Tuple

from app.core.settings import settings
from app.prompts import (
    ANSWER_SYSTEM_PROMPT,
    ANSWER_USER_PROMPT_TEMPLATE,
    INTENT_SYSTEM_PROMPT,
    INTENT_USER_PROMPT_TEMPLATE,
)


@dataclass
class ResponsePipelineConfig:
    """Pipeline configuration settings for response/retrieval flow."""

    # ── Qdrant / VectorDB (sourced from settings) ─────────────────────
    qdrant_url: str = field(default_factory=lambda: settings.QDRANT_URL)
    qdrant_api_key: str = field(default_factory=lambda: settings.QDRANT_API_KEY or "")
    logs_collection_suffix: str = field(default_factory=lambda: settings.QDRANT_LOGS_COLLECTION_SUFFIX)
    commits_collection_suffix: str = field(default_factory=lambda: settings.QDRANT_COMMITS_COLLECTION_SUFFIX)
    postmortem_collection_suffix: str = field(default_factory=lambda: settings.QDRANT_POSTMORTEM_COLLECTION_SUFFIX)

    # ── Retrieval (sourced from settings) ─────────────────────────────
    top_k: int = field(default_factory=lambda: settings.RESPONSE_TOP_K)
    score_threshold: float = field(default_factory=lambda: settings.RESPONSE_SCORE_THRESHOLD)

    # ── Embedding Model (must match ingestion side) ───────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    vector_size: int = 384

    # ── LLM Fallback Chain (Intent Detection & beyond) ────────────────
    # Primary: Gemini. Fallback: Groq llama-3.3-70b-versatile.
    gemini_key: str = field(default_factory=lambda: settings.GEMINI_KEY or "")
    gemini_intent_models: Tuple[str, ...] = ("gemini-2.5-flash",)

    groq_api_key: str = field(default_factory=lambda: settings.GROQ_API_KEY or "")
    groq_api_url: str = "https://api.groq.com/openai/v1/chat/completions"
    groq_intent_model: str = field(default_factory=lambda: settings.GROQ_INTENT_MODEL)

    llm_temperature: float = 0.1
    llm_max_tokens: int = 1024
    llm_timeout: int = 20

    # ── Prompt Templates (sourced from app.prompts) ───────────────────
    intent_system_prompt: str = INTENT_SYSTEM_PROMPT
    intent_user_prompt_template: str = INTENT_USER_PROMPT_TEMPLATE
    answer_system_prompt: str = ANSWER_SYSTEM_PROMPT
    answer_user_prompt_template: str = ANSWER_USER_PROMPT_TEMPLATE

    answer_context_limit: int = 12000
    answer_items_per_bucket: int = 3

    @classmethod
    def from_env(cls) -> "ResponsePipelineConfig":
        """Create config — env values are pulled via app.core.settings."""
        return cls()
