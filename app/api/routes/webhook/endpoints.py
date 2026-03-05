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

    if not x_hub_signature_256:
        logger.warning("Webhook request missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=400,
            detail="Missing X-Hub-Signature-256 header"
        )

    # Verify GitHub webhook signature
    try:
        if not verify_github_signature(body, x_hub_signature_256):
            logger.error("Invalid webhook signature received")
            raise HTTPException(
                status_code=401,
                detail="Invalid signature"
            )
    except RuntimeError as e:
        logger.error(f"Signature verification config error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Signature verification error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Signature verification failed"
        )

    # Parse JSON after verification
    try:
        payload = await request.json()
        event = request.headers.get("X-GitHub-Event", "unknown")
        logger.info(f"GitHub webhook event={event}, ref={payload.get('ref', 'unknown')}")

        # Process push events
        if event == "push" and payload.get("commits"):
            await process_push_event(payload)
            logger.info(f"Processed {len(payload['commits'])} commit(s)")
            return {
                "status": "processed",
                "event": event,
                "commits": len(payload["commits"])
            }
        else:
            logger.info(f"Webhook received but no commits to process (event={event})")
            return {
                "status": "received",
                "event": event,
                "message": "No commits to process"
            }

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing webhook: {str(e)}"
        )

