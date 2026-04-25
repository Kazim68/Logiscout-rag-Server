"""Event processor for GitHub webhook push events."""

import httpx
from datetime import datetime
from typing import Dict

import logging
from app.services.github_webhook_service.groq_client import summarize_diff
from app.services.github_webhook_service.state import add_commit, add_raw_payload

logger = logging.getLogger(__name__)

# Configuration
GITHUB_DIFF_TIMEOUT: int = 15
USER_AGENT: str = "LogiScout-Webhook-Agent"


async def process_push_event(payload: Dict, project_id: str = "default") -> None:
    """
    Process GitHub push event and extract commit information.

    Args:
        payload: GitHub webhook payload
        project_id: LogiScout project ID for scoped storage
    """
    try:
        # Persist original commit payload before any Groq-based processing.
        await add_raw_payload(payload, project_id=project_id)

        repo = payload["repository"]["full_name"]

        # Extract branch name from ref (e.g., "refs/heads/main" -> "main")
        ref = payload.get("ref", "")
        branch = ref.split("/")[-1] if ref.startswith("refs/heads/") else "unknown"

        # Extract pusher information
        pusher_info = payload.get("pusher", {})
        pusher = pusher_info.get("name", "Unknown")

        logger.info("Processing push event for %s, branch: %s, pusher: %s", repo, branch, pusher)

        for commit in payload["commits"]:
            commit_id = commit["id"]
            message = commit["message"]
            author = commit.get("author", {}).get("name", "Unknown")
            timestamp = commit.get("timestamp", datetime.utcnow().isoformat())

            logger.info("Processing commit %s by %s", commit_id[:7], author)

            # Fetch diff asynchronously
            diff_url = commit["url"] + ".patch"

            try:
                async with httpx.AsyncClient(timeout=GITHUB_DIFF_TIMEOUT) as client:
                    response = await client.get(
                        diff_url,
                        headers={
                            "Accept": "application/vnd.github.v3.patch",
                            "User-Agent": USER_AGENT,
                        },
                    )

                if response.status_code != 200 or not response.text.strip():
                    summary = "No diff available for this commit."
                    logger.warning("Could not fetch diff for commit %s", commit_id[:7])
                else:
                    summary = await summarize_diff(response.text)
                    logger.info("Generated summary for commit %s", commit_id[:7])
            except Exception as e:
                logger.error("Error fetching diff for %s: %s", commit_id[:7], e)
                summary = f"Error fetching diff: {e}"

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
                "summary": summary,
            }

            await add_commit(entry, project_id=project_id)

        logger.info("Successfully processed %d commit(s)", len(payload["commits"]))

    except Exception as e:
        logger.error("Error processing push event: %s", e, exc_info=True)
        raise
