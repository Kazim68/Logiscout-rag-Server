"""Centralized configuration for the Response Pipeline.

All environment-derived values are sourced from `app.core.settings.settings`
so the rest of the app has a single source of truth for env vars. Non-env
constants (prompts, model lists, hyperparameters) live here as developer-
configurable defaults.
"""
from dataclasses import dataclass, field
from typing import Tuple

from app.core.settings import settings


# ── Default Intent Detection Prompt ───────────────────────────────────

DEFAULT_INTENT_SYSTEM_PROMPT = """You are an intent classifier for a software incident resolution assistant.
Given the user's prompt (and any prior chat or vague context or not), identify the user's
intent and decide which retrieval sources are needed to answer it.

Respond with a single compact JSON object only. No markdown, no prose.
Schema:
{
  "intent": "<one of: incident_investigation, commit_lookup, code_explanation, status_check, general_question, unknown>",
  "confidence": <float 0..1>,
  "rationale": "<one short sentence>",
  "needs_logs": <true|false>,
  "needs_commits": <true|false>,
  "needs_postmortem": <true|false>
}

Guidelines for the boolean flags:
- needs_logs: true if answering requires any application logs.
- needs_commits: true if answering requires recent code changes / commit history.
- needs_postmortem: true if answering requires past incident postmortems.
Multiple flags may be true. Set them all to false if no retrieval is needed."""

DEFAULT_INTENT_USER_PROMPT_TEMPLATE = """Vague context:
{vague_context}

Chat context:
{chat_context}

User prompt:
{user_prompt}

Classify the intent."""


@dataclass
class ResponsePipelineConfig:
    """Pipeline configuration settings for response/retrieval flow."""

    # ── Qdrant / VectorDB (sourced from settings) ─────────────────────
    qdrant_url: str = field(default_factory=lambda: settings.QDRANT_URL)
    qdrant_api_key: str = field(default_factory=lambda: settings.QDRANT_API_KEY or "")
    collection_suffix: str = field(default_factory=lambda: settings.QDRANT_COMMITS_COLLECTION_SUFFIX)

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

    # ── Intent Prompt Templates ───────────────────────────────────────
    intent_system_prompt: str = DEFAULT_INTENT_SYSTEM_PROMPT
    intent_user_prompt_template: str = DEFAULT_INTENT_USER_PROMPT_TEMPLATE

    @classmethod
    def from_env(cls) -> "ResponsePipelineConfig":
        """Create config — env values are pulled via app.core.settings."""
        return cls()
