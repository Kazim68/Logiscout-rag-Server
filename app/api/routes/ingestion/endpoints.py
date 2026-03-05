"""
Ingestion endpoints – accept raw logs / data for the LLM pipeline.
"""
from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

import logging
from app.db.mongodb.database import get_db
from app.core.constants import STATUS_PENDING

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingestion")


# ── Schemas ───────────────────────────────────────────────────
class IngestionRequest(BaseModel):
    source: str = Field(..., description="Source identifier, e.g. 'github', 'upload'")
    payload: dict = Field(..., description="Raw log / data payload")
    metadata: Optional[dict] = None


class IngestionResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime


# ── Routes ────────────────────────────────────────────────────
@router.post(
    "/",
    response_model=IngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit data for ingestion",
)
async def create_ingestion_job(body: IngestionRequest):
    """
    Accept a payload, persist an ingestion job record in MongoDB,
    and (later) publish to Kafka for async processing.
    """
    db = await get_db()
    job = {
        "source": body.source,
        "payload": body.payload,
        "metadata": body.metadata or {},
        "status": STATUS_PENDING,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = await db.ingestion_jobs.insert_one(job)
    logger.info("Ingestion job created: %s", result.inserted_id)

    # TODO: publish to Kafka topic for pipeline processing

    return IngestionResponse(
        job_id=str(result.inserted_id),
        status=STATUS_PENDING,
        created_at=job["created_at"],
    )


@router.get("/{job_id}", summary="Get ingestion job status")
async def get_ingestion_job(job_id: str):
    from bson import ObjectId

    db = await get_db()
    job = await db.ingestion_jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        return {"error": "Job not found"}
    job["_id"] = str(job["_id"])
    return job
