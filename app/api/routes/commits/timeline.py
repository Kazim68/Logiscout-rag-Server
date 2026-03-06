"""
Commit timeline endpoint — returns the latest commits received via GitHub webhook.
Data is held in-memory; no DB read required.
"""
import logging
from fastapi import APIRouter

from app.services.github_webhook_service.state import get_timeline, get_commit_count

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/timeline", summary="Get live GitHub commit timeline")
async def get_commit_timeline():
    """
    Return the latest 5 GitHub commits stored in the in-memory rolling window.
    Updated in real time whenever the GitHub webhook fires.
    """
    commits = await get_timeline()
    count = await get_commit_count()

    return {
        "total": count,
        "max_commits": 5,
        "commits": commits,
    }
