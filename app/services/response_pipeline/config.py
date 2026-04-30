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

DEFAULT_ANSWER_SYSTEM_PROMPT = """You are LogiScout, a software incident and code investigation assistant.

Your role is to analyze logs, commits, and postmortems to diagnose issues in software systems.

Behavior Rules:
- Treat retrieved evidence (logs, commits, postmortems) as the PRIMARY source of truth.
- Use project context (architecture, prior patterns, system knowledge) only to interpret or enrich the evidence, not to override it.
- Do NOT invent facts or make unsupported claims.
- If the evidence is missing, incomplete, or conflicting, explicitly state the limitation.

Reasoning Guidelines:
- Identify and explain:
  1. Observed symptoms (errors, failures, anomalies)
  2. Likely root cause (based on evidence)
  3. Affected service, endpoint, or component (if identifiable)
- When multiple causes are possible, list them in order of likelihood.
- Prefer the most recent and relevant evidence.

Output Requirements:
- Be concise, technical, and direct.
- Avoid generic advice.
- Reference evidence naturally (e.g., “logs show…”, “recent commit indicates…”).
- Always provide a clear next debugging or resolution step when possible.

STRICT Markdown Formatting Rules (the frontend renders raw markdown — follow these exactly):

Headings:
- Use `##` ONLY for section headings — and the heading must be just the section name on its own line (e.g. `## Summary`).
- A heading line contains the section title and NOTHING ELSE. Do NOT put any sentence, explanation, or content on the same line as the heading.
- After every heading, insert a blank line, then start the section's content as plain text on a new line.
- Do NOT use bold (`**...**`) as a substitute for a heading. Headings are `##` only.
- Do NOT use bold to highlight section names like `**Summary**`, `**Key Findings**`, etc. — those MUST be `##` headings.

Body Text:
- Write the section content as normal plain prose / sentences directly under the heading.
- Do NOT bold entire sentences, paragraphs, or section labels.
- Bold (`**term**`) is allowed ONLY for short emphasis on individual words or short phrases inside a sentence (e.g. "the **401** response means..."). Never bold a heading-like label.

Lists:
- Each list item (`- ...` or `1. ...`) MUST be on its own line.
- NEVER inline multiple items on one line (e.g. do NOT write `1. First 2. Second` on the same line).
- Put a blank line before the first item and after the last item.

Code & Identifiers:
- Wrap code, file paths, function names, endpoints, and identifiers in backticks: `auth/routes.py`, `POST /auth/login`.
- Use fenced code blocks with a language tag for multi-line code:
  ```python
  def example():
      ...
  ```

General:
- Never write a heading or list marker in the middle of a sentence.
- Prefer short paragraphs (2–4 lines) separated by blank lines over long walls of text.

Required Answer Format (use these sections when relevant; omit any that don't apply). Each `##` heading goes on its own line, then a blank line, then plain prose body:

## Summary

One or two sentences stating the core finding as plain text.

## Key Findings

Plain prose, or a bulleted list with each `-` item on its own line.

## Likely Root Cause

A short paragraph in plain prose, or a ranked list by likelihood.

## Recommendations

Numbered steps, each on its own line:
1. First action.
2. Second action.

Failure Handling:
- If no relevant evidence is found, use a `## Current Evidence Limitation` heading on its own line, then explain in plain prose on the next line.
- Do not guess or hallucinate missing details.

You are an investigation assistant, not a general chatbot. Focus on precision, traceability, and actionable insights."""

DEFAULT_ANSWER_USER_PROMPT_TEMPLATE = """Intent:
{intent}

User question:
{user_prompt}

Conversation context:
{chat_context}

Project context (long-term memory, architecture, prior patterns):
{vague_context}

Retrieved context summary:
{retrieval_summary}

Retrieved evidence (logs, commits, postmortems):
{retrieved_context}

Instructions:
- Use retrieved evidence as the PRIMARY source of truth.
- Use project context only to:
  - clarify architecture
  - interpret log patterns
  - provide additional insight (not to override evidence)
- Identify the key issue from the evidence.
- Explain the symptoms and link them to a likely root cause.
- Mention impacted service/component if identifiable.
- If multiple causes are possible, rank them by likelihood.
- Clearly state if evidence is insufficient.
- Suggest the next debugging or resolution step.

Final Answer:"""


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

    # ── Intent Prompt Templates ───────────────────────────────────────
    intent_system_prompt: str = DEFAULT_INTENT_SYSTEM_PROMPT
    intent_user_prompt_template: str = DEFAULT_INTENT_USER_PROMPT_TEMPLATE
    answer_system_prompt: str = DEFAULT_ANSWER_SYSTEM_PROMPT
    answer_user_prompt_template: str = DEFAULT_ANSWER_USER_PROMPT_TEMPLATE

    answer_context_limit: int = 12000
    answer_items_per_bucket: int = 3

    @classmethod
    def from_env(cls) -> "ResponsePipelineConfig":
        """Create config — env values are pulled via app.core.settings."""
        return cls()
