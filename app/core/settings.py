"""
All environment & server configuration for LogiScout.
"""
import os
import re
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, List, Optional


def _parse_dotenv(path: Path) -> Dict[str, str]:
    """Parse a simple KEY=VALUE .env file into a dict. Tolerant of comments,
    blank lines, surrounding quotes, and Windows line endings."""
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def _collect_numbered_keys(prefix: str, env: Dict[str, str]) -> List[str]:
    """Collect non-empty values from `env` for keys named `<prefix>_1`,
    `<prefix>_2`, ... ordered by numeric suffix. Falls back to the legacy
    unsuffixed `<prefix>` if no numbered variants are present."""
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    matches: list[tuple[int, str]] = []
    for name, value in env.items():
        m = pattern.match(name)
        if not m or not value or not value.strip():
            continue
        matches.append((int(m.group(1)), value.strip()))
    matches.sort(key=lambda x: x[0])
    keys = [v for _, v in matches]

    if not keys:
        legacy = env.get(prefix, "").strip()
        if legacy:
            keys = [legacy]
    return keys


def _load_combined_env() -> Dict[str, str]:
    """Merge OS env and the project .env file. .env takes priority to match
    the Settings.settings_customise_sources ordering."""
    combined: Dict[str, str] = dict(os.environ)
    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    combined.update(_parse_dotenv(dotenv_path))
    return combined


_ENV = _load_combined_env()


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
    # GROQ_API_KEY_1..N in .env are tried in order until one succeeds. A
    # legacy single GROQ_API_KEY is honored if no numbered variants exist.
    GROQ_API_KEYS: List[str] = []
    GROQ_INTENT_MODEL: str = "llama-3.3-70b-versatile"

    # ── LLM / Gemini ────────────────────────────────────────
    # GEMINI_KEY_1..N in .env are tried in order until one succeeds. A
    # legacy single GEMINI_KEY is honored if no numbered variants exist.
    GEMINI_KEYS: List[str] = []

    # ── Qdrant (Vector DB) ──────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_LOGS_COLLECTION_SUFFIX: str = "_logs"
    QDRANT_COMMITS_COLLECTION_SUFFIX: str = "_commits"
    QDRANT_POSTMORTEM_COLLECTION_SUFFIX: str = "_postmortem"

    # ── Response Pipeline ───────────────────────────────────
    RESPONSE_TOP_K: int = 5
    RESPONSE_SCORE_THRESHOLD: float = 0.0

    # ── ClickHouse (Related Logs Enrichment) ────────────────
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_DATABASE: str = "logging"
    CLICKHOUSE_LOGS_TABLE: str = "logs"
    CLICKHOUSE_RELATED_LOGS_LIMIT: int = 50

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        """Make .env file override OS environment variables."""
        return (
            init_settings,
            dotenv_settings,    # .env takes priority
            env_settings,       # OS env is fallback
            file_secret_settings,
        )

    def model_post_init(self, __context) -> None:
        """Populate numbered key lists from the combined env after pydantic
        has loaded scalar fields. Pydantic-settings does not expose env vars
        with arbitrary numeric suffixes as List fields, so we collect them
        ourselves from a unified .env + os.environ view."""
        if not self.GEMINI_KEYS:
            self.GEMINI_KEYS = _collect_numbered_keys("GEMINI_KEY", _ENV)
        if not self.GROQ_API_KEYS:
            self.GROQ_API_KEYS = _collect_numbered_keys("GROQ_API_KEY", _ENV)
        if not self.JUDGE_GROQ_API_KEYS:
            self.JUDGE_GROQ_API_KEYS = _collect_numbered_keys("JUDGE_GROQ_API_KEY", _ENV)


settings = Settings()
