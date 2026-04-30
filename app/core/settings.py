"""
All environment & server configuration for LogiScout.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────
    APP_NAME: str = "LogiScout"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENV: str = "development"          # development | staging | production

    # ── API ──────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"

    # ── CORS ────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["*"]

    # ── GitHub Webhook ──────────────────────────────────────
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_REPO: Optional[str] = None            # Format: "owner/repo"
    GITHUB_TOKEN: Optional[str] = None           # For private repos

    # ── LLM / Groq ──────────────────────────────────────────
    GROQ_API_KEY: Optional[str] = None
    GROQ_INTENT_MODEL: str = "llama-3.3-70b-versatile"

    # ── LLM / Gemini ────────────────────────────────────────
    GEMINI_KEY: Optional[str] = None

    # ── Qdrant (Vector DB) ──────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_LOGS_COLLECTION_SUFFIX: str = "_logs"
    QDRANT_COMMITS_COLLECTION_SUFFIX: str = "_commits"
    QDRANT_POSTMORTEM_COLLECTION_SUFFIX: str = "_postmortem"

    # ── Response Pipeline ───────────────────────────────────
    RESPONSE_TOP_K: int = 5
    RESPONSE_SCORE_THRESHOLD: float = 0.0

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        """Make .env file override OS environment variables."""
        return (
            init_settings,
            dotenv_settings,    # .env takes priority
            env_settings,       # OS env is fallback
            file_secret_settings,
        )


settings = Settings()
