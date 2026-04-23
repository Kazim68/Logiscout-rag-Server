"""File-system state management for commit timeline and raw payloads.

Both processed commits and raw GitHub push payloads are stored as rolling
windows of 5 entries in the logs/ directory.  Newest entry is always at
index 0; the oldest is evicted automatically when the window is full.
All files are loaded back into memory on first access so state survives
a server restart.
"""

import asyncio
import json
from collections import deque
from pathlib import Path
from datetime import datetime
from typing import Dict, List

import logging

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────
MAX_COMMITS: int = 5

COMMITS_FILE_PATH: Path = Path("logs/commits.json")
RAW_PAYLOADS_FILE_PATH: Path = Path("logs/raw_commit_payloads.json")
ACTIVITY_LOG_PATH: Path = Path("logs/activity.log")

# ── In-memory rolling windows (index 0 = newest) ─────────────
_commits: deque = deque(maxlen=MAX_COMMITS)
_raw_payloads: deque = deque(maxlen=MAX_COMMITS)

_commits_lock: asyncio.Lock | None = None
_raw_lock: asyncio.Lock | None = None

_commits_loaded: bool = False
_raw_loaded: bool = False


def _get_commits_lock() -> asyncio.Lock:
    global _commits_lock
    if _commits_lock is None:
        _commits_lock = asyncio.Lock()
    return _commits_lock


def _get_raw_lock() -> asyncio.Lock:
    global _raw_lock
    if _raw_lock is None:
        _raw_lock = asyncio.Lock()
    return _raw_lock


# ── Helpers ───────────────────────────────────────────────────

def _ensure_logs_dir() -> None:
    """Create the logs/ directory if it doesn't exist."""
    COMMITS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Processed commits ─────────────────────────────────────────

def _load_commits() -> None:
    """Load persisted processed commits from disk into memory (once)."""
    global _commits_loaded
    if _commits_loaded:
        return
    _commits_loaded = True
    try:
        if COMMITS_FILE_PATH.exists():
            data = json.loads(COMMITS_FILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    _commits.append(entry)
            logger.info("Loaded %d commit(s) from %s", len(_commits), COMMITS_FILE_PATH)
    except Exception as exc:
        logger.error("Error loading commits file: %s", exc)


def _save_commits() -> None:
    """Persist the in-memory commit list to disk (newest first)."""
    try:
        _ensure_logs_dir()
        COMMITS_FILE_PATH.write_text(
            json.dumps(list(_commits), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Error saving commits file: %s", exc)


# ── Raw payloads ──────────────────────────────────────────────

def _load_raw_payloads() -> None:
    """Load persisted raw payloads from disk into memory (once)."""
    global _raw_loaded
    if _raw_loaded:
        return
    _raw_loaded = True
    try:
        if RAW_PAYLOADS_FILE_PATH.exists():
            data = json.loads(RAW_PAYLOADS_FILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    _raw_payloads.append(entry)
            logger.info("Loaded %d raw payload(s) from %s", len(_raw_payloads), RAW_PAYLOADS_FILE_PATH)
    except Exception as exc:
        logger.error("Error loading raw payloads file: %s", exc)


def _save_raw_payloads() -> None:
    """Persist the in-memory raw payload list to disk (newest first)."""
    try:
        _ensure_logs_dir()
        RAW_PAYLOADS_FILE_PATH.write_text(
            json.dumps(list(_raw_payloads), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Error saving raw payloads file: %s", exc)


# ── Activity log ─────────────────────────────────────────────

def _write_activity_log_sync() -> None:
    """Rewrite logs/activity.log from the current in-memory _commits deque.

    Must be called while _commits_lock is held (or from within an
    async-with block that already holds it).
    """
    try:
        _ensure_logs_dir()
        lines = [
            "======================================================================",
            "  LOGISCOUT -- GitHub Commit Activity Log",
            f"  Last Updated: {datetime.utcnow().isoformat()}",
            f"  Total Commits: {len(_commits)} / {MAX_COMMITS}",
            "======================================================================",
            "",
            "----------------------------------------------------------------------",
            f"  CURRENT TIMELINE ({len(_commits)} commits, newest first)",
            "----------------------------------------------------------------------",
            "",
        ]

        for idx, entry in enumerate(_commits, start=1):
            lines.append(f"  [{idx}] {entry.get('commit', '???????')} -- {entry.get('message', 'No message')}")
            lines.append(json.dumps(entry, indent=4, ensure_ascii=False, default=str))
            lines.append("")

        lines.append("======================================================================")
        lines.append("")

        ACTIVITY_LOG_PATH.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        logger.error("Error writing activity log: %s", exc)


async def write_activity_log() -> None:
    """Public async wrapper — acquires the commits lock and rewrites activity.log."""
    async with _get_commits_lock():
        _load_commits()
        _write_activity_log_sync()


# ── Public API ────────────────────────────────────────────────

async def add_raw_payload(payload: Dict) -> None:
    """
    Store the complete GitHub push webhook body.
    Keeps the last 5 payloads in logs/raw_commit_payloads.json (newest first).
    """
    async with _get_raw_lock():
        _load_raw_payloads()

        entry = {
            "received_at": datetime.utcnow().isoformat(),
            **payload,          # full webhook body — every field GitHub sends
        }

        _raw_payloads.appendleft(entry)
        _save_raw_payloads()

        logger.info(
            "Raw payload stored (%d/%d) -> %s",
            len(_raw_payloads), MAX_COMMITS, RAW_PAYLOADS_FILE_PATH,
        )


async def add_commit(entry: Dict) -> None:
    """
    Add a processed commit to the rolling window and persist to disk.
    Newest commit is always at index 0; oldest is evicted when window is full.
    """
    async with _get_commits_lock():
        _load_commits()

        # Skip duplicates
        for existing in _commits:
            if existing.get("full_sha") == entry.get("full_sha"):
                logger.debug("Commit %s already in timeline, skipping", entry.get("commit"))
                return

        entry["created_at"] = datetime.utcnow().isoformat()

        removed = _commits[-1] if len(_commits) == MAX_COMMITS else None
        _commits.appendleft(entry)

        logger.info("Added commit %s (%d/%d)", entry.get("commit"), len(_commits), MAX_COMMITS)
        if removed:
            logger.info("Evicted oldest commit %s", removed.get("commit"))

        _save_commits()
        _write_activity_log_sync()


async def get_timeline() -> List[Dict]:
    """Return the current commit timeline (newest first)."""
    async with _get_commits_lock():
        _load_commits()
        return list(_commits)


async def get_commit_count() -> int:
    """Return the current number of commits in the timeline."""
    async with _get_commits_lock():
        _load_commits()
        return len(_commits)


async def get_raw_payloads() -> List[Dict]:
    """Return the current raw payloads (newest first)."""
    async with _get_raw_lock():
        _load_raw_payloads()
        return list(_raw_payloads)
