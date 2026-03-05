"""Thread-safe state management for commit timeline with MongoDB persistence."""

import json
from pathlib import Path
from datetime import datetime
from threading import Lock
from typing import Dict, List

import logging
from app.db.mongodb.database import get_db

logger = logging.getLogger(__name__)

# Configuration
MAX_COMMITS: int = 5  # Keep only latest 5 commits
ACTIVITY_LOG_PATH: Path = Path("logs/activity.log")
COLLECTION_NAME: str = "github_commits"

# Fields to show in activity.log (mirrors the entry dict)
ENTRY_FIELDS = ["source", "repo", "commit", "full_sha", "message", "author", "pusher", "branch", "timestamp", "summary"]

_lock: Lock = Lock()


def _ensure_logs_dir() -> None:
    """Ensure the logs directory exists."""
    ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _entry_to_json(entry: Dict) -> str:
    """Extract only the relevant entry fields and return pretty JSON."""
    clean = {k: entry.get(k, "") for k in ENTRY_FIELDS}
    return json.dumps(clean, indent=2, ensure_ascii=False, default=str)


async def _write_full_timeline_to_log(action: str, new_entry: Dict = None, removed_entry: Dict = None) -> None:
    """
    Rewrite activity.log with the current DB state.

    The file always contains:
    - A header with timestamp
    - The action that just occurred (ADD / REMOVE)
    - The full list of current 5 (or fewer) commits in JSON
    """
    try:
        _ensure_logs_dir()
        db = await get_db()
        collection = db[COLLECTION_NAME]

        # Fetch current commits from DB (newest first)
        current = await collection.find({}).sort("created_at", -1).limit(MAX_COMMITS).to_list(length=None)

        now = datetime.utcnow().isoformat()
        separator = "=" * 70

        with open(ACTIVITY_LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"{separator}\n")
            f.write(f"  LOGISCOUT — GitHub Commit Activity Log\n")
            f.write(f"  Last Updated: {now}\n")
            f.write(f"  Total Commits: {len(current)} / {MAX_COMMITS}\n")
            f.write(f"{separator}\n\n")

            # Log the action that just happened
            if action and new_entry:
                f.write(f"[{now}] ✅ NEW COMMIT ADDED:\n")
                f.write(f"{_entry_to_json(new_entry)}\n\n")

            if action and removed_entry:
                f.write(f"[{now}] 🗑️  OLDEST COMMIT REMOVED:\n")
                f.write(f"{_entry_to_json(removed_entry)}\n\n")

            # Write the full current timeline
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
    Add a commit entry to MongoDB.
    Maintains a rolling window of exactly MAX_COMMITS (5).
    Rewrites activity.log with full JSON entries after every change.
    """
    try:
        db = await get_db()
        collection = db[COLLECTION_NAME]

        # Check for duplicate
        existing = await collection.find_one({"full_sha": entry.get("full_sha")})
        if existing:
            logger.debug(f"Commit {entry.get('commit')} already exists in DB, skipping")
            return

        # Add timestamps
        entry["created_at"] = datetime.utcnow()
        entry["updated_at"] = datetime.utcnow()

        # Insert new commit
        await collection.insert_one(entry)
        logger.info(f"✅ Added commit {entry.get('commit')} to database")

        # Maintain rolling window — remove oldest if > MAX_COMMITS
        removed_entry = None
        total = await collection.count_documents({})
        if total > MAX_COMMITS:
            oldest = await collection.find({}).sort("created_at", 1).limit(total - MAX_COMMITS).to_list(length=None)
            for old in oldest:
                removed_entry = old  # Keep last removed for logging
                await collection.delete_one({"_id": old["_id"]})
                logger.info(f"🗑️  Removed oldest commit {old.get('commit')}")

        # Rewrite activity.log with full JSON state
        await _write_full_timeline_to_log("change", new_entry=entry, removed_entry=removed_entry)

    except Exception as e:
        logger.error(f"Failed to persist commit to MongoDB: {str(e)}")


async def sync_commits(commits: List[Dict]) -> None:
    """
    Replace all commits in DB with freshly fetched ones (startup / cron).
    Rewrites activity.log with the full JSON timeline.
    """
    if not commits:
        logger.warning("No commits to sync")
        return

    try:
        db = await get_db()
        collection = db[COLLECTION_NAME]

        # Clear existing
        await collection.delete_many({})

        # Insert new (limit to MAX_COMMITS)
        for commit in commits[:MAX_COMMITS]:
            commit["created_at"] = datetime.utcnow()
            commit["updated_at"] = datetime.utcnow()
            await collection.insert_one(commit)
            logger.info(f"Synced commit {commit.get('commit')} to database")

        logger.info(f"Successfully synced {len(commits[:MAX_COMMITS])} commits to database")

        # Rewrite activity.log
        await _write_full_timeline_to_log("sync")

    except Exception as e:
        logger.error(f"Failed to sync commits to MongoDB: {str(e)}")


async def get_timeline() -> List[Dict]:
    """Retrieve the current commit timeline from MongoDB (newest first)."""
    try:
        db = await get_db()
        collection = db[COLLECTION_NAME]

        commits = await collection.find({}).sort("created_at", -1).limit(MAX_COMMITS).to_list(length=None)
        for commit in commits:
            commit["_id"] = str(commit["_id"])
        return commits
    except Exception as e:
        logger.error(f"Failed to retrieve timeline: {str(e)}")
        return []


async def get_commit_count() -> int:
    """Get the current number of commits in database."""
    try:
        db = await get_db()
        return await db[COLLECTION_NAME].count_documents({})
    except Exception as e:
        logger.error(f"Failed to get commit count: {str(e)}")
        return 0


async def clear_timeline() -> None:
    """Clear all commits from database and activity log."""
    try:
        db = await get_db()
        result = await db[COLLECTION_NAME].delete_many({})
        logger.info(f"Cleared {result.deleted_count} commits from database")
        await _write_full_timeline_to_log("clear")
    except Exception as e:
        logger.error(f"Failed to clear timeline: {str(e)}")

