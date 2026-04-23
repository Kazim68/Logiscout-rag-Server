"""Groq LLM client for commit diff summarization."""

import httpx

from app.core.settings import settings
import logging

logger = logging.getLogger(__name__)

# Configuration
GROQ_API_URL: str = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL: str = "llama-3.1-8b-instant"
MAX_DIFF_CHARS: int = 3500
LLM_TEMPERATURE: float = 0.3
LLM_MAX_TOKENS: int = 300
REQUEST_TIMEOUT: int = 20


async def summarize_diff(diff_text: str) -> str:
    """
    Generate an LLM-powered summary of a Git commit diff.

    Args:
        diff_text: The raw Git diff text

    Returns:
        Summary text or error message
    """
    if not settings.GROQ_API_KEY:
        logger.warning("Groq API key not configured")
        return "LLM summarization unavailable (GROQ_API_KEY not set)"

    # Truncate large diffs
    diff_text = diff_text[:MAX_DIFF_CHARS]

    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Summarize this Git commit diff clearly and concisely:\n\n"
                    f"{diff_text}"
                )
            }
        ],
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                GROQ_API_URL,
                headers=headers,
                json=payload,
            )

        if response.status_code != 200:
            logger.error("Groq API error %d: %s", response.status_code, response.text)
            return f"LLM API error: {response.status_code}"

        return response.json()["choices"][0]["message"]["content"]

    except Exception as e:
        logger.error("Groq API exception: %s", e)
        return f"LLM summarization failed: {e}"
