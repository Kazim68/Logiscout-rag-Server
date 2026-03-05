"""
LogiScout – Main FastAPI application entry point.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.settings import settings
import logging
from app.core.logging_config import setup_logging
from app.db.mongodb.database import init_db, close_db
from app.api.router import api_router
from app.cron.scheduler.scheduler import start_scheduler, stop_scheduler
from app.services.github_webhook_service.github_client import fetch_recent_commits
from app.services.github_webhook_service.state import sync_commits, get_commit_count

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hooks."""
    setup_logging()
    logger.info("Starting LogiScout server …")
    
    # Initialize MongoDB
    await init_db()
    logger.info("MongoDB connected")
    
    # Initialize GitHub commits on startup
    if settings.GITHUB_REPO:
        try:
            logger.info(f"Fetching latest commits from {settings.GITHUB_REPO}...")
            commits = fetch_recent_commits(count=5)
            if commits:
                await sync_commits(commits)
                count = await get_commit_count()
                logger.info(f"✅ Initialized with {count} commits from GitHub")
            else:
                logger.warning("No commits fetched from GitHub on startup")
        except Exception as e:
            logger.error(f"Failed to initialize GitHub commits: {str(e)}")
    else:
        logger.warning("GITHUB_REPO not configured - skipping commit initialization")
    
    # Start cron scheduler for periodic sync
    start_scheduler()
    
    yield
    
    # Shutdown
    logger.info("Shutting down …")
    stop_scheduler()
    await close_db()


# ── App factory ───────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="LogiScout – Intelligent log ingestion & analytics platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Exception handlers ───────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "Validation Error", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    detail = str(exc) if settings.DEBUG else "An unexpected error occurred"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal Server Error", "detail": detail},
    )


# ── Register routers ─────────────────────────────────────────
app.include_router(api_router)
