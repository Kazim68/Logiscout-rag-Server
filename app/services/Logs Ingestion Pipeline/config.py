"""Centralized configuration for LogiScout pipeline."""
import os
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class Config:
    """Pipeline configuration settings."""

    # ── Qdrant / VectorDB ─────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    vector_size: int = 384  # BGE-small dimensions

    # Collection names
    collection_logs: str = "logiscout_logs"
    collection_incidents: str = "logiscout_incidents"
    collection_commits: str = "logiscout_commits"

    # ── LLM ───────────────────────────────────────────────────────────
    gemini_key: str = field(default_factory=lambda: os.getenv("GEMINI_KEY", "AIzaSyCW5nrX8PGa6Sqgs86cG4OjYXCBGLCltQA"))
    models_to_try: Tuple[str, ...] = ("gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite")

    # ── OLAP / Spark Fetcher ──────────────────────────────────────────
    olap_jdbc_url: str = field(default_factory=lambda: os.getenv("OLAP_JDBC_URL", "jdbc:postgresql://localhost:5432/logiscout"))
    olap_table: str = field(default_factory=lambda: os.getenv("OLAP_TABLE", "application_logs"))
    olap_driver: str = field(default_factory=lambda: os.getenv("OLAP_DRIVER", "org.postgresql.Driver"))
    olap_user: str = field(default_factory=lambda: os.getenv("OLAP_USER", "postgres"))
    olap_password: str = field(default_factory=lambda: os.getenv("OLAP_PASSWORD", ""))

    # ── Scheduler / Batch ─────────────────────────────────────────────
    fetch_interval_minutes: int = 5
    fetch_batch_size: int = 1000
    watermark_path: str = field(default_factory=lambda: os.getenv("WATERMARK_PATH", ".watermark"))

    # ── Vector Store ──────────────────────────────────────────────────
    upsert_batch_size: int = 100            # batch size for Qdrant upserts
    hf_hub_offline: bool = True             # set HF_HUB_OFFLINE env var

    @classmethod
    def from_env(cls) -> "Config":
        """Create config from environment variables."""
        return cls(
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            gemini_key=os.getenv("GEMINI_KEY", ""),
            olap_jdbc_url=os.getenv("OLAP_JDBC_URL", "jdbc:postgresql://localhost:5432/logiscout"),
            olap_table=os.getenv("OLAP_TABLE", "application_logs"),
            olap_driver=os.getenv("OLAP_DRIVER", "org.postgresql.Driver"),
            olap_user=os.getenv("OLAP_USER", "postgres"),
            olap_password=os.getenv("OLAP_PASSWORD", ""),
            fetch_interval_minutes=int(os.getenv("FETCH_INTERVAL_MINUTES", "5")),
            fetch_batch_size=int(os.getenv("FETCH_BATCH_SIZE", "1000")),
            watermark_path=os.getenv("WATERMARK_PATH", ".watermark"),
            upsert_batch_size=int(os.getenv("UPSERT_BATCH_SIZE", "100")),
            hf_hub_offline=os.getenv("HF_HUB_OFFLINE", "1") == "1",
        )
