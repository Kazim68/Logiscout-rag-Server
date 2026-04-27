"""
Intent-Detection LLM fallback chain.

Tries Gemini models first, then falls back to Groq. If every provider
fails, raises LLMUnavailableError so callers can surface a clean error.

All network calls are async — Gemini via its async API, Groq via httpx.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when every provider in the fallback chain has failed."""


class LLMClient:
    """Async LLM client implementing a Gemini → Groq fallback chain."""

    def __init__(self, config):
        self.config = config
        self._gemini_module = None

    # ── Gemini ────────────────────────────────────────────────────────

    def _get_gemini_module(self):
        if self._gemini_module is None:
            import google.generativeai as genai
            if not self.config.gemini_key:
                raise RuntimeError("GEMINI_KEY not configured")
            genai.configure(api_key=self.config.gemini_key)
            self._gemini_module = genai
            logger.info("Gemini client initialized")
        return self._gemini_module

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        models: tuple,
    ) -> Optional[str]:
        try:
            genai = self._get_gemini_module()
        except Exception as e:
            logger.warning("Gemini unavailable (init failed): %s", e)
            return None

        for model_name in models:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt,
                )
                response = await model.generate_content_async(
                    user_prompt,
                    generation_config={
                        "temperature": self.config.llm_temperature,
                        "max_output_tokens": self.config.llm_max_tokens,
                    },
                )
                text = getattr(response, "text", None)
                if text and text.strip():
                    logger.info("Gemini OK via model: %s", model_name)
                    return text
                logger.warning("Gemini model %s returned empty response", model_name)
            except Exception as e:
                logger.warning("Gemini model %s failed: %s", model_name, e)
                continue

        logger.error("All Gemini models failed: %s", models)
        return None

    # ── Groq ──────────────────────────────────────────────────────────

    async def _call_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> Optional[str]:
        if not self.config.groq_api_key:
            logger.warning("Groq fallback skipped: GROQ_API_KEY not configured")
            return None

        headers = {
            "Authorization": f"Bearer {self.config.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.llm_temperature,
            "max_tokens": self.config.llm_max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.config.llm_timeout) as client:
                resp = await client.post(
                    self.config.groq_api_url,
                    headers=headers,
                    json=payload,
                )

            if resp.status_code != 200:
                logger.error("Groq API error %d: %s", resp.status_code, resp.text[:300])
                return None

            content = resp.json()["choices"][0]["message"]["content"]
            if content and content.strip():
                logger.info("Groq OK via model: %s", model)
                return content
            logger.warning("Groq model %s returned empty response", model)
            return None
        except Exception as e:
            logger.error("Groq API exception: %s", e)
            return None

    # ── Public API ────────────────────────────────────────────────────

    async def complete_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Run the full Gemini → Groq fallback chain for a single completion.

        Raises LLMUnavailableError if every provider fails.
        """
        text = await self._call_gemini(
            system_prompt, user_prompt, self.config.gemini_intent_models,
        )
        if text:
            return text

        logger.warning("Gemini chain exhausted — falling back to Groq")
        text = await self._call_groq(
            system_prompt, user_prompt, self.config.groq_intent_model,
        )
        if text:
            return text

        logger.error(
            "LLM fallback chain exhausted — Gemini=%s, Groq=%s",
            list(self.config.gemini_intent_models),
            self.config.groq_intent_model,
        )
        raise LLMUnavailableError(
            "LLM service not available — both Gemini and Groq providers failed."
        )
