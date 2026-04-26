"""LLM Summarizer Service: Multi-provider commit diff summarization (Gemini or Groq)."""

import logging
from typing import Optional

import requests

from .models import (
    RawCommitPayload, FetchedCommitDetail, DiffAnalysis, LLMCommitSummary,
)

logger = logging.getLogger(__name__)


class LLMSummarizerService:
    """
    Handles LLM interaction for commit diff summarization.

    Supports configurable provider: "gemini" (via google.generativeai) or
    "groq" (via HTTP API, reused from OLD_GITHUB_PIPELINE/groq_client.py).
    Switching requires only an .env change — no code changes.
    """

    def __init__(self, config):
        self.config = config
        self._gemini_client = None

    # ── 1. Gemini Client ──────────────────────────────────────────────

    def _create_gemini_client(self):
        """Initializes and caches the Gemini client."""
        if self._gemini_client is None:
            import google.generativeai as genai
            genai.configure(api_key=self.config.gemini_key)
            self._gemini_client = genai
            logger.info("Gemini client initialized")
        return self._gemini_client

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Sends the prompt to Gemini with model fallback.

        Same pattern as LLMService in the LLM Response Pipeline.
        Returns raw response text, or None if all models fail.
        """
        genai = self._create_gemini_client()

        for model_name in self.config.gemini_models_to_try:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt,
                )
                response = model.generate_content(user_prompt)
                logger.info(f"Gemini response generated using model: {model_name}")
                return response.text
            except Exception as e:
                logger.warning(f"Gemini model {model_name} failed: {e}")
                continue

        logger.error(f"All Gemini models failed: {self.config.gemini_models_to_try}")
        return None

    # ── 2. Groq Client (reused from OLD_GITHUB_PIPELINE/groq_client.py) ──

    def _call_groq(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Sends the prompt to Groq via HTTP API.

        Reused logic from OLD_GITHUB_PIPELINE/groq_client.py, adapted from
        async httpx to sync requests for consistency with this pipeline.
        """
        if not self.config.groq_api_key:
            logger.warning("Groq API key not configured")
            return None

        headers = {
            "Authorization": f"Bearer {self.config.groq_api_key}",
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
                logger.error("Groq API error %d: %s", response.status_code, response.text[:300])
                return None

            result = response.json()["choices"][0]["message"]["content"]
            logger.info("Groq response generated using model: %s", self.config.groq_model)
            return result

        except Exception as e:
            logger.error("Groq API exception: %s", e)
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
