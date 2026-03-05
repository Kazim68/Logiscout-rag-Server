"""Event processor for GitHub webhook push events."""

import requests
from datetime import datetime
from typing import Dict

import logging
from app.services.github_webhook_service.groq_client import summarize_diff
from app.services.github_webhook_service.state import add_commit

logger = logging.getLogger(__name__)

# Configuration
GITHUB_DIFF_TIMEOUT: int = 15
USER_AGENT: str = "LogiScout-Webhook-Agent"


async def process_push_event(payload: Dict) -> None:
    """
    Process GitHub push event and extract commit information.
    
    Args:
        payload: GitHub webhook payload
    """
    try:
        repo = payload["repository"]["full_name"]
        
        # Extract branch name from ref (e.g., "refs/heads/main" -> "main")
        ref = payload.get("ref", "")
        branch = ref.split("/")[-1] if ref.startswith("refs/heads/") else "unknown"
        
        # Extract pusher information
        pusher_info = payload.get("pusher", {})
        pusher = pusher_info.get("name", "Unknown")
        
        logger.info(f"Processing push event for {repo}, branch: {branch}, pusher: {pusher}")

        for commit in payload["commits"]:
            commit_id = commit["id"]
            message = commit["message"]
            author = commit.get("author", {}).get("name", "Unknown")
            timestamp = commit.get("timestamp", datetime.utcnow().isoformat())

            logger.info(f"Processing commit {commit_id[:7]} by {author}")

            # Fetch diff
            diff_url = commit["url"] + ".patch"

            try:
                response = requests.get(
                    diff_url,
                    headers={
                        "Accept": "application/vnd.github.v3.patch",
                        "User-Agent": USER_AGENT
                    },
                    timeout=GITHUB_DIFF_TIMEOUT
                )

                if response.status_code != 200 or not response.text.strip():
                    summary = "No diff available for this commit."
                    logger.warning(f"Could not fetch diff for commit {commit_id[:7]}")
                else:
                    summary = summarize_diff(response.text)
                    logger.info(f"Generated summary for commit {commit_id[:7]}")
            except Exception as e:
                logger.error(f"Error fetching diff for {commit_id[:7]}: {str(e)}")
                summary = f"Error fetching diff: {str(e)}"

            entry = {
                "source": "github_webhook",
                "repo": repo,
                "commit": commit_id[:7],
                "full_sha": commit_id,
                "message": message,
                "author": author,
                "pusher": pusher,
                "branch": branch,
                "timestamp": timestamp,
                "summary": summary
            }

            await add_commit(entry)
            
        logger.info(f"Successfully processed {len(payload['commits'])} commit(s)")
        
    except Exception as e:
        logger.error(f"Error processing push event: {str(e)}", exc_info=True)
        raise
