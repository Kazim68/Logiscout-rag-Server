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
from app.api.router import api_router
from app.services.github_webhook_service.state import (
    COMMITS_FILE_PATH,
    RAW_PAYLOADS_FILE_PATH,
    ACTIVITY_LOG_PATH,
)
from app.services.github_webhook_service.github_api import fetch_and_populate_commits

logger = logging.getLogger(__name__)


def _init_logs() -> None:
    """Create the logs/ directory and seed JSON files on first run."""
    COMMITS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

    for path in (COMMITS_FILE_PATH, RAW_PAYLOADS_FILE_PATH):
        if not path.exists():
            path.write_text("[]", encoding="utf-8")
            logger.info("Created log file: %s", path)
        else:
            logger.info("Log file ready: %s", path)

    if not ACTIVITY_LOG_PATH.exists():
        ACTIVITY_LOG_PATH.write_text("", encoding="utf-8")
        logger.info("Created log file: %s", ACTIVITY_LOG_PATH)
    else:
        logger.info("Log file ready: %s", ACTIVITY_LOG_PATH)


# ── Lifespan ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hooks."""
    setup_logging()
    logger.info("Starting LogiScout server …")
    _init_logs()
    await fetch_and_populate_commits()
    yield
    logger.info("Shutting down …")


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
