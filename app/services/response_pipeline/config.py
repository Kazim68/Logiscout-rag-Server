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

    # ── ClickHouse (Related Logs Enrichment) ──────────────────────────
    clickhouse_host: str = field(default_factory=lambda: settings.CLICKHOUSE_HOST)
    clickhouse_port: int = field(default_factory=lambda: settings.CLICKHOUSE_PORT)
    clickhouse_user: str = field(default_factory=lambda: settings.CLICKHOUSE_USER)
    clickhouse_password: str = field(default_factory=lambda: settings.CLICKHOUSE_PASSWORD)
    clickhouse_database: str = field(default_factory=lambda: settings.CLICKHOUSE_DATABASE)
    clickhouse_logs_table: str = field(default_factory=lambda: settings.CLICKHOUSE_LOGS_TABLE)
    clickhouse_related_logs_limit: int = field(default_factory=lambda: settings.CLICKHOUSE_RELATED_LOGS_LIMIT)

    # ── Embedding Model (must match ingestion side) ───────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    vector_size: int = 384

    # ── LLM Fallback Chain (Intent Detection & beyond) ────────────────
    # Primary: Gemini. Fallback: Groq llama-3.3-70b-versatile.
    # Each provider accepts a list of API keys — the fallback chain rotates
    # through them in order, retrying on rate limits / auth errors / any
    # provider-side failure before giving up on the provider.
    gemini_keys: Tuple[str, ...] = field(
        default_factory=lambda: tuple(settings.GEMINI_KEYS)
    )
    gemini_intent_models: Tuple[str, ...] = ("gemini-3.1-flash-lite",)

    groq_api_keys: Tuple[str, ...] = field(
        default_factory=lambda: tuple(settings.GROQ_API_KEYS)
    )
    groq_api_url: str = "https://api.groq.com/openai/v1/chat/completions"
    groq_intent_model: str = field(default_factory=lambda: settings.GROQ_INTENT_MODEL)

    @property
    def gemini_key(self) -> str:
        """First configured Gemini key, or empty string. Backward-compat
        accessor for callers that only need a single key."""
        return self.gemini_keys[0] if self.gemini_keys else ""

    @property
    def groq_api_key(self) -> str:
        """First configured Groq key, or empty string. Backward-compat
        accessor for callers that only need a single key."""
        return self.groq_api_keys[0] if self.groq_api_keys else ""

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
