"""
Health-check endpoints.
"""
from fastapi import APIRouter
from app.core.settings import settings

router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@router.get("/ready", summary="Readiness probe")
async def readiness():
    """
    Extend this to verify DB / Kafka connectivity before returning healthy.
    """
    return {"status": "ready"}
