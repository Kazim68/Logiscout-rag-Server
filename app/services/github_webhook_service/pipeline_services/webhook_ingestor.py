"""Webhook Ingestor Service: Validates, strips, and queues GitHub commit payloads to MongoDB."""

import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

from .models import RawCommitPayload

logger = logging.getLogger(__name__)


class WebhookIngestorService:
    """Receives raw GitHub commit objects, strips noise, and queues to MongoDB."""

    def __init__(self, config):
        self.config = config
        self._client = None
        self._collection = None

    # ── 1. MongoDB Connection ─────────────────────────────────────────

    def _get_collection(self):
        """Creates and caches the MongoDB collection handle."""
        if self._collection is None:
            self._client = MongoClient(self.config.mongo_uri)
            db = self._client[self.config.mongo_db]
            self._collection = db[self.config.mongo_collection]

            # Ensure unique index on commit_sha for deduplication
            self._collection.create_index("commit_sha", unique=True)
            # Secondary indexes for worker queries
            self._collection.create_index([("status", ASCENDING), ("received_at", ASCENDING)])

            logger.info(
                "MongoDB connected — db=%s, collection=%s",
                self.config.mongo_db, self.config.mongo_collection,
            )
        return self._collection

    # ── 2. Strip Noise Fields ─────────────────────────────────────────

    def _strip_noise(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively removes noisy fields from the raw GitHub commit payload.

        Strips:
        - commit.verification (entire block — PGP signature)
        - All fields ending in _url at any nesting level
        - node_id, gravatar_id at any nesting level
        - user_view_type, site_admin, comment_count
        - committer object if committer.login == "web-flow" (GitHub UI merge bot)
        """
        if not isinstance(payload, dict):
            return payload

        # Remove committer if it's the GitHub web-flow merge bot
        committer = payload.get("committer")
        if isinstance(committer, dict) and committer.get("login") == "web-flow":
            payload.pop("committer", None)

        # Remove verification from commit object
        commit_obj = payload.get("commit")
        if isinstance(commit_obj, dict):
            commit_obj.pop("verification", None)

        keys_to_remove = []
        for key in payload:
            if key.endswith("_url"):
                keys_to_remove.append(key)
            elif key in ("node_id", "gravatar_id", "user_view_type", "site_admin", "comment_count"):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            payload.pop(key, None)

        # Recurse into nested dicts and lists
        for key, value in list(payload.items()):
            if isinstance(value, dict):
                payload[key] = self._strip_noise(value)
            elif isinstance(value, list):
                payload[key] = [
                    self._strip_noise(item) if isinstance(item, dict) else item
                    for item in value
                ]

        return payload

    # ── 3. Extract Stripped Payload ────────────────────────────────────

    def _extract_payload(self, raw_commit: Dict[str, Any], branch: str) -> RawCommitPayload:
        """
        Extracts the minimal payload to store in MongoDB.

        Derives 'repo' from html_url since the raw commit object has no top-level repo field.
        """
        html_url = raw_commit.get("html_url", "")

        # Parse owner/repo from URL: https://github.com/owner/repo/commit/sha
        repo = "unknown/unknown"
        match = re.search(r"github\.com/([^/]+/[^/]+)", html_url)
        if match:
            repo = match.group(1)

        # Navigate into nested commit object for author details
        commit_obj = raw_commit.get("commit", {})
        author_obj = commit_obj.get("author", {})
        # Top-level author has login info
        top_author = raw_commit.get("author", {}) or {}

        parents = [p["sha"] if isinstance(p, dict) else p for p in raw_commit.get("parents", [])]

        return RawCommitPayload(
            sha=raw_commit.get("sha", ""),
            repo=repo,
            author_login=top_author.get("login", "unknown"),
            author_name=author_obj.get("name", "unknown"),
            committed_at=author_obj.get("date", ""),
            commit_message=commit_obj.get("message", ""),
            branch=branch,
            html_url=html_url,
            parents=parents,
        )

    # ── 4. Detect Merge Commit ────────────────────────────────────────

    def _is_merge_commit(self, raw_commit: Dict[str, Any]) -> bool:
        """Returns True if the commit has more than one parent (merge commit)."""
        return len(raw_commit.get("parents", [])) > 1

    # ── 5. Ingest Commits ─────────────────────────────────────────────

    def ingest(self, raw_commits: List[Dict[str, Any]], branch: str = "unknown") -> Dict[str, int]:
        """
        Processes a list of raw GitHub commit dicts from a webhook push event.

        For each commit:
        1. Strips noise fields
        2. Extracts minimal payload
        3. Detects merge commits (stores with status='skipped')
        4. Upserts into MongoDB with $setOnInsert for deduplication

        Args:
            raw_commits: List of raw commit dicts from the GitHub webhook.
            branch: Branch name extracted from the push event ref.

        Returns:
            Dict with counts: {"queued": N, "skipped_merge": N, "duplicate": N}
        """
        collection = self._get_collection()
        counts = {"queued": 0, "skipped_merge": 0, "duplicate": 0}

        for raw_commit in raw_commits:
            # Strip noise from the raw payload
            stripped = self._strip_noise(dict(raw_commit))

            # Extract the minimal payload
            payload = self._extract_payload(stripped, branch)

            # Determine status
            is_merge = self._is_merge_commit(raw_commit)
            status = "skipped" if is_merge else "pending"

            if is_merge:
                logger.info(
                    "Merge commit detected — SHA=%s, parents=%d, status=skipped",
                    payload.sha[:8], len(payload.parents),
                )

            # Upsert with $setOnInsert — if SHA already exists, document is not
            # overwritten and status is not reset. This is the dedup guarantee.
            now = datetime.now(timezone.utc)
            doc = {
                **payload.model_dump(),
                "commit_sha": payload.sha,
                "status": status,
                "retry_count": 0,
                "error_message": None,
                "received_at": now,
                "processed_at": None,
            }

            result = collection.update_one(
                {"commit_sha": payload.sha},
                {"$setOnInsert": doc},
                upsert=True,
            )

            if result.upserted_id is not None:
                # New document was inserted
                if is_merge:
                    counts["skipped_merge"] += 1
                else:
                    counts["queued"] += 1
            else:
                # Document already existed — duplicate
                counts["duplicate"] += 1
                logger.debug("Duplicate commit skipped — SHA=%s", payload.sha[:8])

        logger.info(
            "Webhook ingestion complete — queued=%d, skipped_merge=%d, duplicate=%d",
            counts["queued"], counts["skipped_merge"], counts["duplicate"],
        )
        return counts
