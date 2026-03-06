"""
Central API router – aggregates all route modules.
"""
from fastapi import APIRouter

from app.core.settings import settings
from app.api.routes.ingestion.endpoints import router as ingestion_router
from app.api.routes.webhook.endpoints import router as webhook_router
from app.api.routes.analytics.endpoints import router as analytics_router

api_router = APIRouter()

# Versioned routes
v1 = settings.API_V1_PREFIX
api_router.include_router(ingestion_router, prefix=v1, tags=["ingestion"])
api_router.include_router(webhook_router, prefix=v1, tags=["webhook"])
api_router.include_router(analytics_router, prefix=v1, tags=["analytics"])
