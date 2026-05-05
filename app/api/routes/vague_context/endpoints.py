"""
Vague-context maintenance endpoints.

POST /vague_context/summarize
    Update a project's evergreen "vague context" by folding in the
    rolling chat_summary plus the latest few raw messages from a session.
    Returns {"vague_context": "<new value>"}.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.response_pipeline.config import ResponsePipelineConfig
from app.services.vague_context_service import VagueContextSummarizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vague_context")


class VagueContextSummarizeRequest(BaseModel):
    project_id: str = Field(..., description="Project ID owning the vague context.")
    chat_summary: Optional[Any] = Field(
        default=None,
        description="Rolling chat_summary for the session that just produced activity.",
    )
    recent_messages: Optional[Any] = Field(
        default=None,
        description="Latest 6–8 raw messages from the session, most recent last.",
    )
    current_vague_context: Optional[Any] = Field(
        default=None,
        description="Current vague context for the project (may be null/empty on first run).",
    )


# Single shared summarizer; reuses the cached LLMClient initialization.
_summarizer = VagueContextSummarizer(ResponsePipelineConfig.from_env())


@router.post("/summarize", summary="Update a project's vague context from a chat session")
async def summarize_vague_context(payload: VagueContextSummarizeRequest):
    logger.info(
        "VagueContext summarize request — project=%s",
        payload.project_id,
    )

    result = await _summarizer.summarize(
        project_id=payload.project_id,
        chat_summary=payload.chat_summary,
        recent_messages=payload.recent_messages,
        current_vague_context=payload.current_vague_context,
    )

    return {
        "vague_context": result.vague_context,
        "provider": result.provider,
        "error": result.error,
    }
