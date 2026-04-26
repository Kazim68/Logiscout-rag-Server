"""Event processor for GitHub webhook push events (v2 pipeline).

Bridge between the FastAPI endpoint and the v2 commit ingestion pipeline.
Processes commits directly — no MongoDB queue, no worker.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict

from app.services.github_webhook_service.config import CommitPipelineConfig
from app.services.github_webhook_service.pipeline import CommitIngestionPipeline
from app.services.github_webhook_service.state import add_commit, add_raw_payload

logger = logging.getLogger(__name__)


async def process_push_event(payload: Dict, project_id: str = "default") -> None:
    """
    Process GitHub push event through the v2 commit ingestion pipeline.

    For each commit:
    1. Fetches full commit detail from GitHub API
    2. Runs deterministic diff analysis
    3. Generates LLM summary
    4. Prepares vector-ready document
    5. Upserts to Qdrant ({project_id}_commits collection)
    6. Updates rolling window + activity log

    Args:
        payload: GitHub webhook push event payload
        project_id: LogiScout project ID for scoped storage
    """
    try:
        # Persist original webhook payload (rolling window for timeline)
        await add_raw_payload(payload, project_id=project_id)

        repo = payload["repository"]["full_name"]

        # Extract branch name from ref (e.g., "refs/heads/main" -> "main")
        ref = payload.get("ref", "")
        branch = ref.split("/")[-1] if ref.startswith("refs/heads/") else "unknown"

        # Extract pusher information
        pusher = payload.get("pusher", {}).get("name", "Unknown")

        logger.info("Processing push event for %s, branch: %s, pusher: %s", repo, branch, pusher)

        config = CommitPipelineConfig.from_env()
        pipeline = CommitIngestionPipeline(config)

        for commit in payload["commits"]:
            commit_id = commit["id"]
            message = commit["message"]
            author = commit.get("author", {}).get("name", "Unknown")
            timestamp = commit.get("timestamp", datetime.utcnow().isoformat())

            logger.info("Processing commit %s by %s through v2 pipeline", commit_id[:7], author)

            # Run v2 pipeline stages (sync code — run in thread to avoid blocking event loop)
            commit_doc = await asyncio.to_thread(
                pipeline.process_webhook_commit,
                commit_data=commit,
                repo=repo,
                branch=branch,
                project_id=project_id,
            )

            # Build timeline entry and add to rolling window
            entry = {
                "project_id": project_id,
                "source": "github_webhook",
                "repo": repo,
                "commit": commit_id[:7],
                "full_sha": commit_id,
                "message": message,
                "author": author,
                "pusher": pusher,
                "branch": branch,
                "timestamp": timestamp,
                "summary": commit_doc.semantic_text if commit_doc else "Processing failed",
            }

            await add_commit(entry, project_id=project_id)

        logger.info(
            "Successfully processed %d commit(s) for project %s",
            len(payload["commits"]), project_id,
        )

    except Exception as e:
        logger.error("Error processing push event: %s", e, exc_info=True)
        raise
