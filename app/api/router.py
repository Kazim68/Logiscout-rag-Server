"""
Central API router – aggregates all route modules.
"""
from fastapi import APIRouter

from app.core.settings import settings
from app.api.routes.webhook.endpoints import router as webhook_router
from app.api.routes.commits.router import router as commits_router
from app.api.routes.response.endpoints import router as response_router
from app.api.routes.vague_context.endpoints import router as vague_context_router
from app.api.routes.chat_summary.endpoints import router as chat_summary_router

api_router = APIRouter()

# Versioned routes
v1 = settings.API_V1_PREFIX
api_router.include_router(webhook_router, prefix=v1, tags=["webhook"])
api_router.include_router(commits_router, prefix=v1, tags=["commits"])
api_router.include_router(response_router, prefix=v1, tags=["response"])
api_router.include_router(vague_context_router, prefix=v1, tags=["vague_context"])
api_router.include_router(chat_summary_router, prefix=v1, tags=["chat_summary"])
