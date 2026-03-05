"""
Analytics endpoints – query processed logs / OLAP aggregates.
"""
from fastapi import APIRouter, Query
from typing import Optional

import logging
from app.db.mongodb.database import get_db
from app.services.github_webhook_service.state import get_timeline, get_commit_count

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics")


@router.get("/github-commits", summary="Get GitHub commits timeline")
async def get_github_commits():
    """
    Return the latest 5 GitHub commits stored in the database.
    This timeline is automatically synced via cron job every 5 minutes.
    """
    commits = await get_timeline()
    count = await get_commit_count()
    
    return {
        "total": count,
        "max_commits": 5,
        "commits": commits,
        "note": "Timeline syncs every 5 minutes via cron job"
    }


@router.get("/logs", summary="Query processed logs from MongoDB")
async def get_processed_logs(
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(20, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """
    Return processed logs stored in MongoDB after the LLM pipeline.
    """
    db = await get_db()
    query: dict = {}
    if source:
        query["source"] = source

    cursor = db.processed_logs.find(query).skip(skip).limit(limit).sort("created_at", -1)
    logs = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        logs.append(doc)

    return {"count": len(logs), "logs": logs}


@router.get("/summary", summary="High-level analytics summary")
async def analytics_summary():
    """
    Placeholder – will aggregate data from ClickHouse / BigQuery
    once olap_service is implemented.
    """
    return {"message": "Analytics summary – coming soon"}
