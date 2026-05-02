"""
Chat session summary endpoint.

POST /chat_summary
    Update a chat session's rolling summary. Triggered every 10 new
    messages by the caller. Returns {"chat_summary": "<new value>"}.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.chat_summary_service import ChatSummarizer
from app.services.response_pipeline.config import ResponsePipelineConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat_summary")


class ChatSummaryRequest(BaseModel):
    project_id: str = Field(..., description="Project ID owning the chat session.")
    chat_id: str = Field(..., description="Chat session ID this summary belongs to.")
    previous_summary: Optional[Any] = Field(
        default=None,
        description="Existing rolling summary for this chat (may be null/empty on first run).",
    )
    new_messages: Optional[Any] = Field(
        default=None,
        description="The latest batch of new messages (typically 10) to fold into the summary.",
    )


_summarizer = ChatSummarizer(ResponsePipelineConfig.from_env())


@router.post("", summary="Update a chat session's rolling summary")
async def summarize_chat(payload: ChatSummaryRequest):
    logger.info(
        "ChatSummary request — project=%s, chat=%s",
        payload.project_id,
        payload.chat_id,
    )

    result = await _summarizer.summarize(
        project_id=payload.project_id,
        chat_id=payload.chat_id,
        previous_summary=payload.previous_summary,
        new_messages=payload.new_messages,
    )

    return {
        "chat_summary": result.chat_summary,
        "provider": result.provider,
        "error": result.error,
    }
