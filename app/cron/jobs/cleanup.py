"""
Cron job for syncing GitHub commits to database.
Periodically fetches latest commits and maintains rolling window of 5 commits.
"""
import asyncio
import logging
from app.services.github_webhook_service.github_client import fetch_recent_commits
from app.services.github_webhook_service.state import sync_commits

logger = logging.getLogger(__name__)


async def sync_github_commits_job():
    """
    Periodic job to sync latest GitHub commits to database.
    Maintains a rolling window of the latest 5 commits.
    """
    try:
        logger.info("Starting GitHub commits sync job...")
        
        # Fetch latest 5 commits from GitHub
        commits = fetch_recent_commits(count=5)
        
        if not commits:
            logger.warning("No commits fetched from GitHub")
            return
        
        # Sync commits to database (replaces old ones)
        await sync_commits(commits)
        
        logger.info(f"GitHub commits sync job completed successfully ({len(commits)} commits)")
        
    except Exception as e:
        logger.error(f"Error in GitHub commits sync job: {str(e)}", exc_info=True)


def run_sync_job():
    """Wrapper to run the async job in a synchronous context."""
    try:
        asyncio.run(sync_github_commits_job())
    except Exception as e:
        logger.error(f"Failed to run sync job: {str(e)}")

