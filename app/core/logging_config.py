"""
Structured logging configuration for LogiScout.
"""
import logging
import sys

from app.core.settings import settings

# Third-party loggers to silence (only show WARNING+)
_NOISY_LOGGERS = [
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "motor",
    "pymongo",
    "apscheduler",
    "httpx",
    "httpcore",
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "asyncio",
    "watchfiles",
    "multipart",
]


def setup_logging() -> None:
    """Configure root logger for the application."""
    app_level = logging.DEBUG if settings.DEBUG else logging.INFO

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.WARNING)  # default: quiet
    # avoid duplicate handlers on reload
    if not root.handlers:
        root.addHandler(handler)

    # App loggers at desired level
    logging.getLogger("app").setLevel(app_level)

    # Keep uvicorn.access at INFO so you see request lines
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    # Silence noisy third-party loggers
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)



