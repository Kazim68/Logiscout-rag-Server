"""In-memory state management for commit timeline with activity.log persistence."""

import json
from collections import deque
from pathlib import Path
from datetime import datetime
from threading import Lock
from typing import Dict, List

import logging

logger = logging.getLogger(__name__)

# Configuration
MAX_COMMITS: int = 5  # Keep only the latest 5 commits
ACTIVITY_LOG_PATH: Path = Path("logs/activity.log")

# Fields written to activity.log
ENTRY_FIELDS = ["source", "repo", "commit", "full_sha", "message", "author", "pusher", "branch", "timestamp", "summary"]

# In-memory rolling window — index 0 is newest, index -1 is oldest
_commits: deque = deque(maxlen=MAX_COMMITS)
_lock: Lock = Lock()


def _ensure_logs_dir() -> None:
    """Ensure the logs directory exists."""
    ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _entry_to_json(entry: Dict) -> str:
    """Extract only the relevant entry fields and return pretty JSON."""
    clean = {k: entry.get(k, "") for k in ENTRY_FIELDS}
    return json.dumps(clean, indent=2, ensure_ascii=False, default=str)


def _write_full_timeline_to_log(new_entry: Dict = None, removed_entry: Dict = None) -> None:
    """Rewrite activity.log with the current in-memory commit list."""
    try:
        _ensure_logs_dir()
        current = list(_commits)  # snapshot (newest first)
        now = datetime.utcnow().isoformat()
        separator = "=" * 70

        with open(ACTIVITY_LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"{separator}\n")
            f.write(f"  LOGISCOUT — GitHub Commit Activity Log\n")
            f.write(f"  Last Updated: {now}\n")
            f.write(f"  Total Commits: {len(current)} / {MAX_COMMITS}\n")
            f.write(f"{separator}\n\n")

            if new_entry:
                f.write(f"[{now}] NEW COMMIT ADDED:\n")
                f.write(f"{_entry_to_json(new_entry)}\n\n")

            if removed_entry:
                f.write(f"[{now}] OLDEST COMMIT REMOVED:\n")
                f.write(f"{_entry_to_json(removed_entry)}\n\n")

            f.write(f"{'-' * 70}\n")
            f.write(f"  CURRENT TIMELINE ({len(current)} commits, newest first)\n")
            f.write(f"{'-' * 70}\n\n")

            for idx, commit in enumerate(current, 1):
                clean = {k: commit.get(k, "") for k in ENTRY_FIELDS}
                f.write(f"  [{idx}] {clean['commit']} — {clean['message']}\n")
                f.write(f"{json.dumps(clean, indent=4, ensure_ascii=False, default=str)}\n\n")

            f.write(f"{separator}\n")

    except Exception as e:
        logger.error(f"Error writing to activity log: {str(e)}")


async def add_commit(entry: Dict) -> None:
    """
    Add a commit to the in-memory rolling window and update activity.log.
    Maintains the latest MAX_COMMITS (5) commits at all times.

    Future: pass entry through an LLM pipeline here, then store the
    processed result in MongoDB before this function returns.
    """
    with _lock:
        # Skip duplicates
        for existing in _commits:
            if existing.get("full_sha") == entry.get("full_sha"):
                logger.debug(f"Commit {entry.get('commit')} already in timeline, skipping")
                return

        entry["created_at"] = datetime.utcnow().isoformat()

        # Capture the commit that will be evicted (oldest, at the right end)
        removed_entry = _commits[-1] if len(_commits) == MAX_COMMITS else None

        # appendleft keeps newest at index 0; auto-evicts from the right when full
        _commits.appendleft(entry)

        logger.info(f"Added commit {entry.get('commit')} to timeline ({len(_commits)}/{MAX_COMMITS})")
        if removed_entry:
            logger.info(f"Removed oldest commit {removed_entry.get('commit')} from timeline")

    _write_full_timeline_to_log(new_entry=entry, removed_entry=removed_entry)


async def get_timeline() -> List[Dict]:
    """Return the current in-memory commit timeline (newest first)."""
    with _lock:
        return list(_commits)


async def get_commit_count() -> int:
    """Return the current number of commits in the in-memory timeline."""
    with _lock:
        return len(_commits)

