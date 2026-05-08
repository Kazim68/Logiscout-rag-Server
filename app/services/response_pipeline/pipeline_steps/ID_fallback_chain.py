"""
Intent-Detection LLM fallback chain.

Tries each Gemini API key (across the configured models) first, then each
Groq API key. A provider is only considered exhausted once every key fails.
If every provider fails, raises LLMUnavailableError so callers can surface
a clean error.

All network calls are async — Gemini via its async API, Groq via httpx.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when every provider in the fallback chain has failed."""


def _mask(key: str) -> str:
    """Render a key as a short suffix for logs without leaking the secret."""
    if not key:
        return "<empty>"
    return f"...{key[-4:]}" if len(key) > 4 else "***"


class LLMClient:
    """Async LLM client implementing a Gemini → Groq fallback chain with
    multi-key rotation per provider."""

    def __init__(self, config):
        self.config = config

    # ── Gemini ────────────────────────────────────────────────────────

    async def _call_gemini_with_key(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        models: tuple,
    ) -> Optional[str]:
        """Try every model under a single API key. Returns text on first
        success, None if every model fails for this key."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
        except Exception as e:
            logger.warning("Gemini init failed for key %s: %s", _mask(api_key), e)
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
                    logger.info(
                        "Gemini OK via model=%s key=%s", model_name, _mask(api_key),
                    )
                    return text
                logger.warning(
                    "Gemini model=%s key=%s returned empty response",
                    model_name, _mask(api_key),
                )
            except Exception as e:
                logger.warning(
                    "Gemini model=%s key=%s failed: %s",
                    model_name, _mask(api_key), e,
                )
                continue
        return None

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        models: tuple,
    ) -> Optional[str]:
        keys = tuple(self.config.gemini_keys)
        if not keys:
            logger.warning("Gemini skipped: no GEMINI_KEY_* configured")
            return None

        for api_key in keys:
            text = await self._call_gemini_with_key(
                api_key, system_prompt, user_prompt, models,
            )
            if text:
                return text
            logger.warning(
                "Gemini key %s exhausted across all models — rotating",
                _mask(api_key),
            )

        logger.error(
            "All Gemini keys (%d) failed across models %s", len(keys), models,
        )
        return None

    # ── Groq ──────────────────────────────────────────────────────────

    async def _call_groq_with_key(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
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
                logger.error(
                    "Groq API error %d (key=%s): %s",
                    resp.status_code, _mask(api_key), resp.text[:300],
                )
                return None

            content = resp.json()["choices"][0]["message"]["content"]
            if content and content.strip():
                logger.info("Groq OK via model=%s key=%s", model, _mask(api_key))
                return content
            logger.warning(
                "Groq model=%s key=%s returned empty response", model, _mask(api_key),
            )
            return None
        except Exception as e:
            logger.error("Groq API exception (key=%s): %s", _mask(api_key), e)
            return None

    async def _call_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> Optional[str]:
        keys = tuple(self.config.groq_api_keys)
        if not keys:
            logger.warning("Groq fallback skipped: no GROQ_API_KEY_* configured")
            return None

        for api_key in keys:
            text = await self._call_groq_with_key(
                api_key, system_prompt, user_prompt, model,
            )
            if text:
                return text
            logger.warning("Groq key %s failed — rotating", _mask(api_key))

        logger.error("All Groq keys (%d) failed for model %s", len(keys), model)
        return None

    # ── Public API ────────────────────────────────────────────────────

    async def complete_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Run the full Gemini → Groq fallback chain for a single completion.
        Each provider rotates through its full set of API keys before the
        chain advances to the next provider.

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
            "LLM fallback chain exhausted — Gemini models=%s keys=%d, Groq model=%s keys=%d",
            list(self.config.gemini_intent_models),
            len(self.config.gemini_keys),
            self.config.groq_intent_model,
            len(self.config.groq_api_keys),
        )
        raise LLMUnavailableError(
            "LLM service not available — both Gemini and Groq providers failed."
        )
