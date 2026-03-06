"""
Processed logs endpoint — returns LLM-processed commit records from MongoDB.
This is the read side of the future LLM pipeline output.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Query

from app.db.mongodb.database import get_db
from app.core.constants import COLLECTION_PROCESSED_LOGS

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/logs", summary="Query processed commit logs")
async def get_processed_logs(
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(20, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """
    Return processed commit records stored in MongoDB after the LLM pipeline.
    Populated once the LLM processing stage is implemented.
    """
    db = await get_db()
    query: dict = {}
    if source:
        query["source"] = source

    cursor = db[COLLECTION_PROCESSED_LOGS].find(query).skip(skip).limit(limit).sort("created_at", -1)
    logs = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        logs.append(doc)

    return {"count": len(logs), "logs": logs}
