"""
Commit timeline endpoint — returns the latest commits received via GitHub webhook.
Data is held in-memory; no DB read required.
"""
import logging
from fastapi import APIRouter

from app.services.github_webhook_service.state import (
    get_timeline, get_commit_count, get_raw_payloads,
    get_project_timeline, get_project_commit_count, get_project_raw_payloads,
)

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
    raw = await get_raw_payloads()

    return {
        "total": count,
        "max_commits": 5,
        "commits": commits,
        "raw_payloads": raw,
    }


@router.get("/{project_id}/timeline", summary="Get project-scoped commit timeline")
async def get_project_commit_timeline(project_id: str):
    """
    Return the latest 5 GitHub commits for a specific project.
    """
    commits = await get_project_timeline(project_id)
    count = await get_project_commit_count(project_id)
    raw = await get_project_raw_payloads(project_id)

    return {
        "project_id": project_id,
        "total": count,
        "max_commits": 5,
        "commits": commits,
        "raw_payloads": raw,
    }
