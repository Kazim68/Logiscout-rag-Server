"""Load /app/.env (or project .env) into os.environ for evaluation scripts.

The RAG server uses pydantic-settings which reads .env directly, so the docker
container itself does not export CLICKHOUSE_* / EVAL_PROJECT_ID as OS env vars.
The evaluation scripts read straight from os.environ, so we hydrate it here.

Importing this module at the top of every evaluation entrypoint is enough.
"""
import os
from pathlib import Path


def _candidates() -> list[Path]:
    here = Path(__file__).resolve()
    return [
        Path("/app/.env"),
        here.parent.parent / ".env",
        here.parent / ".env",
    ]


def load_env() -> None:
    for path in _candidates():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            # Do not clobber values that were explicitly set in the env.
            os.environ.setdefault(key, value)
        break

    # Default for the evaluation project id if not set anywhere.
    os.environ.setdefault("EVAL_PROJECT_ID", "69fcea90cbb613a79de43939")


load_env()
