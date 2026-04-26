"""Centralized configuration for the Commit Ingestion Pipeline."""
import os
from dataclasses import dataclass, field
from typing import Tuple, List, Dict


# ── Default Prompt Template ───────────────────────────────────────────
# Plain English summary — no JSON output required.

DEFAULT_COMMIT_SYSTEM_PROMPT = """You are a code change analyst for a software incident response system.
Your job is to analyze git diffs and produce a clear, plain-English summary of what technically changed.
Be precise, technical, and brief. Focus on what actually changed functionally.
Respond with one paragraph only. No bullet points. No JSON. No markdown formatting."""

DEFAULT_COMMIT_USER_PROMPT_TEMPLATE = """Commit by {author} on {repo} (branch: {branch}).
Original commit message: "{commit_message}"

Files changed:
{files_changed_list}

Diff:
{diff_content}

Summarize what technically changed in this commit in one clear paragraph."""


# ── Default Classification Rules ──────────────────────────────────────

DEFAULT_CHANGE_TYPE_RULES: List[Tuple[str, str]] = [
    ("**/migrations/**",        "schema_migration"),
    ("**/alembic/**",           "schema_migration"),
    ("**/alembic.ini",          "schema_migration"),
    ("requirements*.txt",       "dependency_update"),
    ("**/package.json",         "dependency_update"),
    ("**/pyproject.toml",       "dependency_update"),
    ("**/poetry.lock",          "dependency_update"),
    ("config/**",               "config_change"),
    ("**/*.yml",                "config_change"),
    ("**/*.yaml",               "config_change"),
    ("**/*.env*",               "config_change"),
    ("**/settings*.py",         "config_change"),
    ("**/test_*",               "test"),
    ("**/*_test.*",             "test"),
    ("tests/**",                "test"),
    ("**/*.md",                 "docs"),
    ("docs/**",                 "docs"),
    ("README*",                 "docs"),
]

DEFAULT_RISK_RULES: List[Tuple[str, str]] = [
    ("**/migrations/**",        "critical"),
    ("**/alembic/**",           "critical"),
    ("src/auth/**",             "critical"),
    ("src/payment/**",          "critical"),
    ("src/billing/**",          "critical"),
    ("config/**",               "high"),
    ("**/*.yml",                "high"),
    ("**/*.yaml",               "high"),
    ("**/*.env*",               "high"),
    ("src/**",                  "medium"),
    ("**/*.py",                 "medium"),
    ("**/*.js",                 "medium"),
    ("tests/**",                "low"),
    ("**/*.md",                 "low"),
    ("docs/**",                 "low"),
]

DEFAULT_SERVICE_PATH_MAPPING: Dict[str, str] = {
    "src/inventory/":   "inventory-api",
    "src/auth/":        "auth-service",
    "src/payment/":     "payment-service",
    "src/billing/":     "billing-service",
    "src/user/":        "user-service",
    "src/db/":          "database",
    "config/db":        "database",
}

# Priority order — higher index = higher priority
CHANGE_TYPE_PRIORITY = [
    "unknown", "docs", "test", "config_change",
    "dependency_update", "schema_migration",
]

RISK_PRIORITY = ["low", "medium", "high", "critical"]


@dataclass
class CommitPipelineConfig:
    """Pipeline configuration settings."""

    # ── GitHub API ────────────────────────────────────────────────────
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    github_api_base: str = field(default_factory=lambda: os.getenv("GITHUB_API_BASE", "https://api.github.com"))
    github_webhook_secret: str = field(default_factory=lambda: os.getenv("GITHUB_WEBHOOK_SECRET", ""))

    # ── Qdrant / VectorDB ─────────────────────────────────────────────
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333"))
    collection_commits: str = field(default_factory=lambda: os.getenv("QDRANT_COMMITS_COLLECTION", "logiscout_commits"))
    vector_size: int = 384  # BGE-small dimensions, not configurable via env

    # ── LLM (configurable provider) ───────────────────────────────────
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gemini"))  # "gemini" or "groq"

    # Gemini settings
    gemini_key: str = field(default_factory=lambda: os.getenv("GEMINI_KEY", ""))
    gemini_models_to_try: Tuple[str, ...] = ("gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite")

    # Groq settings (reused from OLD_GITHUB_PIPELINE)
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_api_url: str = "https://api.groq.com/openai/v1/chat/completions"
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))
    groq_temperature: float = 0.3
    groq_max_tokens: int = 300
    groq_timeout: int = 20



    # ── Diff ──────────────────────────────────────────────────────────
    max_diff_chars: int = 4000

    # ── Vector Store ──────────────────────────────────────────────────
    upsert_batch_size: int = 100

    # ── Prompt Templates (developer-configurable, not env vars) ───────
    commit_system_prompt: str = DEFAULT_COMMIT_SYSTEM_PROMPT
    commit_user_prompt_template: str = DEFAULT_COMMIT_USER_PROMPT_TEMPLATE

    # ── Classification Rules (developer-configurable, not env vars) ───
    change_type_rules: List[Tuple[str, str]] = field(default_factory=lambda: list(DEFAULT_CHANGE_TYPE_RULES))
    risk_rules: List[Tuple[str, str]] = field(default_factory=lambda: list(DEFAULT_RISK_RULES))
    service_path_mapping: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SERVICE_PATH_MAPPING))

    @classmethod
    def from_env(cls) -> "CommitPipelineConfig":
        """Create config from environment variables."""
        return cls(
            github_token=os.getenv("GITHUB_TOKEN", ""),
            github_api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
            github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            collection_commits=os.getenv("QDRANT_COMMITS_COLLECTION", "logiscout_commits"),
            llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
            gemini_key=os.getenv("GEMINI_KEY", ""),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            max_diff_chars=int(os.getenv("MAX_DIFF_CHARS", "4000")),
        )
