"""
Baseline pipeline: simulates a developer dumping raw ClickHouse logs into
a plain Gemini LLM call with no vector retrieval and no enrichment.

Gemini-only by user request — both Groq keys are exhausted with long
retry-after windows. All Gemini calls go through the global rolling-window
rate limiter so we stay under the 10 req/min free-tier limit.
"""
from evaluation import env_loader  # noqa: F401

import os
import time
from typing import Tuple

import clickhouse_connect
import httpx

from evaluation.rate_limiter import gemini_acquire


GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _gemini_key() -> str:
    return os.environ.get("BASELINE_GEMINI_KEY") or os.environ.get("GEMINI_KEY") or ""


def get_ch_client():
    return clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", 8123)),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "logging"),
    )


def fetch_all_raw_logs(project_id: str, limit: int = 150) -> list[dict]:
    """All recent logs for the project, no correlation filter."""
    client = get_ch_client()
    table = os.environ.get("CLICKHOUSE_LOGS_TABLE", "logs")
    result = client.query(
        f"SELECT correlationId, timestamp, level, message, loggerName "
        f"FROM {table} "
        f"WHERE projectId = %(project_id)s "
        f"ORDER BY timestamp DESC "
        f"LIMIT %(limit)s",
        parameters={"project_id": project_id, "limit": limit},
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def _build_prompt(query: str, log_dump: str) -> str:
    return (
        f"I am a developer investigating a production incident. "
        f"Here are my application logs:\n\n{log_dump}\n\n"
        f"Question: {query}\n\n"
        f"Please identify the root cause and provide specific next steps to resolve it."
    )


def run_baseline(query: str, project_id: str, max_retries: int = 6) -> Tuple[str, str]:
    raw_logs = fetch_all_raw_logs(project_id)

    log_dump = "\n".join(
        f"[{row.get('timestamp', '')}] [{str(row.get('level', '')).upper()}] "
        f"({row.get('loggerName', '')}) {row.get('message', '')} "
        f"[corr={row.get('correlationId', '')}]"
        for row in raw_logs
    )

    prompt = _build_prompt(query, log_dump)

    api_key = _gemini_key()
    if not api_key:
        return "[Baseline failed: no Gemini API key configured]", log_dump

    url = GEMINI_URL_TEMPLATE.format(model=GEMINI_MODEL)
    body = {
        "contents": [{"parts": [{"text": prompt}], "role": "user"}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }

    last_err: Exception | None = None
    for attempt in range(max_retries):
        gemini_acquire()
        try:
            resp = httpx.post(url, params={"key": api_key}, json=body, timeout=90)
            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after else 30.0 * (attempt + 1)
                wait = min(wait, 90.0)
                print(f"  [Baseline/Gemini] 429; sleeping {wait:.1f}s "
                      f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise ValueError(f"empty candidates: {data}")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                raise ValueError("empty Gemini response text")
            return text, log_dump
        except Exception as e:
            last_err = e
            time.sleep(min(20.0, 2 ** attempt))

    return f"[Baseline failed: {last_err}]", log_dump
