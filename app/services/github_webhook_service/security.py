"""Security module for GitHub webhook signature verification."""

import hmac
import hashlib
from typing import Optional

from app.core.settings import settings
import logging

logger = logging.getLogger(__name__)


def verify_github_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature.
    
    Args:
        payload: Raw request body as bytes
        signature: X-Hub-Signature-256 header value
    
    Returns:
        True if signature is valid, False otherwise
    
    Raises:
        RuntimeError: If GITHUB_WEBHOOK_SECRET is not configured
    """
    if not settings.GITHUB_WEBHOOK_SECRET:
        raise RuntimeError("GITHUB_WEBHOOK_SECRET not configured in .env")

    mac = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        msg=payload,
        digestmod=hashlib.sha256
    )
    expected = "sha256=" + mac.hexdigest()

    return hmac.compare_digest(expected, signature)
