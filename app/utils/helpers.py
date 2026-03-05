"""
Small shared helpers.
"""
from datetime import datetime


def utcnow() -> datetime:
    """Return current UTC time (timezone-naive, consistent across the app)."""
    return datetime.utcnow()
