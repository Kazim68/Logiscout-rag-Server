"""LLM Summarizer Service: Multi-provider commit diff summarization (Gemini or Groq)."""

import logging
from typing import Optional

import requests

from .models import (
    RawCommitPayload, FetchedCommitDetail, DiffAnalysis, LLMCommitSummary,
)

logger = logging.getLogger(__name__)


def _mask(key: str) -> str:
    if not key:
        return "<empty>"
    return f"...{key[-4:]}" if len(key) > 4 else "***"


class LLMSummarizerService:
    """
    Handles LLM interaction for commit diff summarization.

    Supports configurable provider: "gemini" (via google.generativeai) or
    "groq" (via HTTP API, reused from OLD_GITHUB_PIPELINE/groq_client.py).
    Each provider rotates through every configured API key
    (GEMINI_KEY_1..N / GROQ_API_KEY_1..N) before giving up.
    Switching requires only an .env change — no code changes.
    """

    def __init__(self, config):
        self.config = config

    # ── 1. Gemini Client ──────────────────────────────────────────────

    def _call_gemini_with_key(
        self, api_key: str, system_prompt: str, user_prompt: str,
    ) -> Optional[str]:
        """Try every model under a single Gemini API key."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
        except Exception as e:
            logger.warning("Gemini init failed for key %s: %s", _mask(api_key), e)
            return None

        for model_name in self.config.gemini_models_to_try:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt,
                )
                response = model.generate_content(user_prompt)
                logger.info(
                    "Gemini OK via model=%s key=%s", model_name, _mask(api_key),
                )
                return response.text
            except Exception as e:
                logger.warning(
                    "Gemini model=%s key=%s failed: %s",
                    model_name, _mask(api_key), e,
                )
                continue
        return None

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Rotate through every Gemini key. Returns raw response text on first
        success, or None if every key/model combination fails."""
        keys = tuple(self.config.gemini_keys)
        if not keys:
            logger.warning("Gemini skipped: no GEMINI_KEY_* configured")
            return None

        for api_key in keys:
            text = self._call_gemini_with_key(api_key, system_prompt, user_prompt)
            if text:
                return text
            logger.warning(
                "Gemini key %s exhausted across all models — rotating",
                _mask(api_key),
            )

        logger.error(
            "All Gemini keys (%d) failed across models %s",
            len(keys), self.config.gemini_models_to_try,
        )
        return None

    # ── 2. Groq Client (reused from OLD_GITHUB_PIPELINE/groq_client.py) ──

    def _call_groq_with_key(
        self, api_key: str, system_prompt: str, user_prompt: str,
    ) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.groq_temperature,
            "max_tokens": self.config.groq_max_tokens,
        }

        try:
            response = requests.post(
                self.config.groq_api_url,
                headers=headers,
                json=payload,
                timeout=self.config.groq_timeout,
            )

            if response.status_code != 200:
                logger.error(
                    "Groq API error %d (key=%s): %s",
                    response.status_code, _mask(api_key), response.text[:300],
                )
                return None

            result = response.json()["choices"][0]["message"]["content"]
            logger.info(
                "Groq OK via model=%s key=%s",
                self.config.groq_model, _mask(api_key),
            )
            return result

        except Exception as e:
            logger.error("Groq API exception (key=%s): %s", _mask(api_key), e)
            return None

    def _call_groq(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Rotate through every Groq key."""
        keys = tuple(self.config.groq_api_keys)
        if not keys:
            logger.warning("Groq skipped: no GROQ_API_KEY_* configured")
            return None

        for api_key in keys:
            text = self._call_groq_with_key(api_key, system_prompt, user_prompt)
            if text:
                return text
            logger.warning("Groq key %s failed — rotating", _mask(api_key))

        logger.error(
            "All Groq keys (%d) failed for model %s",
            len(keys), self.config.groq_model,
        )
        return None

    # ── 3. Dispatch to Provider ───────────────────────────────────────

    def _call_llm(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Routes to the configured LLM provider."""
        provider = self.config.llm_provider.lower()

        if provider == "gemini":
            return self._call_gemini(system_prompt, user_prompt)
        elif provider == "groq":
            return self._call_groq(system_prompt, user_prompt)
        else:
            logger.error("Unknown LLM provider: %s (expected 'gemini' or 'groq')", provider)
            return None

    # ── 4. Build Prompt ───────────────────────────────────────────────

    def _build_user_prompt(
        self,
        fetched: FetchedCommitDetail,
        raw_payload: RawCommitPayload,
    ) -> str:
        """
        Builds the user prompt from the config template and commit data.

        Uses .patch diff if available (richer content), otherwise falls back
        to concatenated per-file patches from the API response.
        """
        files_changed_list = "\n".join(
            f"{f.status}: {f.filename}" for f in fetched.files
        )

        # Prefer the .patch diff if available (reused from OLD_GITHUB_PIPELINE)
        if fetched.patch_diff:
            diff_content = fetched.patch_diff[:self.config.max_diff_chars]
        else:
            # Fall back to concatenated per-file patches from API
            diff_content = "\n\n".join(
                f"--- {f.filename} ---\n{f.patch}"
                for f in fetched.files
                if f.patch
            )

        if not diff_content:
            diff_content = "(no diff available — binary or oversized files only)"

        return self.config.commit_user_prompt_template.format(
            author=raw_payload.author_login,
            repo=raw_payload.repo,
            branch=raw_payload.branch,
            commit_message=raw_payload.commit_message,
            files_changed_list=files_changed_list,
            diff_content=diff_content,
        )

    # ── 5. Summarize (Public Entry Point) ─────────────────────────────

    def summarize(
        self,
        fetched: FetchedCommitDetail,
        diff_analysis: DiffAnalysis,
        raw_payload: RawCommitPayload,
    ) -> LLMCommitSummary:
        """
        Sends the commit diff to the configured LLM and returns a plain-text summary.

        On failure: falls back to raw commit message, sets llm_failed = True.
        Never crashes the pipeline.
        """
        user_prompt = self._build_user_prompt(fetched, raw_payload)
        system_prompt = self.config.commit_system_prompt

        # Call the configured LLM provider
        summary_text = self._call_llm(system_prompt, user_prompt)

        if summary_text and summary_text.strip():
            # Truncate if excessively long
            if len(summary_text) > 1000:
                summary_text = summary_text[:1000]

            return LLMCommitSummary(
                summary=summary_text.strip(),
                llm_failed=False,
            )

        # LLM failed — fall back to raw commit message
        logger.warning(
            "LLM summarization failed for SHA=%s — using commit message fallback",
            raw_payload.sha[:8],
        )
        return LLMCommitSummary(
            summary=raw_payload.commit_message,
            llm_failed=True,
        )
