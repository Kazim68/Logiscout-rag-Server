"""
Commits router — assembles all commit-related sub-routers under /commits.
"""
from fastapi import APIRouter

from app.api.routes.commits.timeline import router as timeline_router
from app.api.routes.commits.logs import router as logs_router

router = APIRouter(prefix="/commits")

router.include_router(timeline_router, tags=["commits"])
router.include_router(logs_router, tags=["commits"])
