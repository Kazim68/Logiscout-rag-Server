"""
GitHub / external webhook endpoints.
"""
from fastapi import APIRouter, Request, Header, HTTPException, status

import logging
from app.services.github_webhook_service.security import verify_github_signature
from app.services.github_webhook_service.processor import process_push_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook")


@router.post("/github", status_code=status.HTTP_200_OK, summary="GitHub webhook receiver")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256")
):
    """
    Receive GitHub webhook events with signature verification.
    Processes push events and stores them in MongoDB.
    """
    # Read raw body (required for signature verification)
    body = await request.body()
    logger.info("incoming request body: %s", body)

    if not x_hub_signature_256:
        logger.warning("Webhook request missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=400,
            detail="Missing X-Hub-Signature-256 header"
        )

    # Verify GitHub webhook signature
    try:
        is_valid = verify_github_signature(body, x_hub_signature_256)
    except RuntimeError as e:
        logger.error("Signature verification config error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("Signature verification error: %s", e)
        raise HTTPException(status_code=500, detail="Signature verification failed")

    if not is_valid:
        logger.error("Invalid webhook signature received")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON after verification
    try:
        payload = await request.json()
        event = request.headers.get("X-GitHub-Event", "unknown")
        logger.info("GitHub webhook event=%s, ref=%s", event, payload.get("ref", "unknown"))

        # Handle ping event (sent when webhook is first created)
        if event == "ping":
            logger.info("Received GitHub ping event — webhook is configured correctly")
            return {
                "status": "pong",
                "event": event,
                "zen": payload.get("zen", ""),
            }

        # Process push events
        if event == "push" and payload.get("commits"):
            await process_push_event(payload)
            logger.info("Processed %d commit(s)", len(payload["commits"]))
            return {
                "status": "processed",
                "event": event,
                "commits": len(payload["commits"]),
            }

        logger.info("Webhook received but no commits to process (event=%s)", event)
        return {
            "status": "received",
            "event": event,
            "message": "No commits to process",
        }

    except Exception as e:
        logger.error("Error processing webhook: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing webhook: {e}",
        )

