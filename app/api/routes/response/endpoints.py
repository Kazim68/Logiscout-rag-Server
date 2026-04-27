"""
Response generation endpoint — runs the Response Pipeline and streams
output back to the client over chunked HTTP (newline-delimited JSON).
"""
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.response_pipeline import ResponsePipeline, ResponsePipelineConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/response")


class ResponseRequest(BaseModel):
    vague_context: Optional[Any] = Field(
        default=None,
        description="Vague/background context relevant to the conversation.",
    )
    chat_context: Optional[Any] = Field(
        default=None,
        description="Prior chat turns or conversation history.",
    )
    user_prompt: str = Field(
        ...,
        description="The user's current prompt/question.",
    )
    project_id: str = Field(
        ...,
        description="Project ID used to scope the Qdrant collection lookup.",
    )


# Single shared pipeline instance — Qdrant client and (later) embedding model
# are cached on it for reuse across requests.
_pipeline = ResponsePipeline(ResponsePipelineConfig.from_env())


@router.post("", summary="Generate a response (chunked stream)")
async def generate_response(payload: ResponseRequest):
    """
    Run the response pipeline and stream chunks back to the client.

    Each chunk is a newline-delimited JSON object of the form:
        {"event": "<status|intent|answer|error|done>", "data": {...}}

    The `answer` event includes retrieval context keys:
        log_context, commit_context, postmartems_context

    A terminal `done` event is always emitted by the pipeline.
    """
    logger.info(
        "Response request — project=%s, prompt_len=%d",
        payload.project_id,
        len(payload.user_prompt),
    )

    async def _iter():
        try:
            async for chunk in _pipeline.run_stream(
                vague_context=payload.vague_context,
                chat_context=payload.chat_context,
                user_prompt=payload.user_prompt,
                project_id=payload.project_id,
            ):
                yield chunk
        except Exception as e:
            # The pipeline itself emits its own terminal `done` event, so this
            # path only fires if the iterator setup itself blew up.
            logger.error("Response pipeline failed: %s", e, exc_info=True)
            yield json.dumps({"event": "error", "data": {"message": str(e)}}) + "\n"
            yield json.dumps({"event": "done", "data": {"ok": False, "sources": []}}) + "\n"

    return StreamingResponse(_iter(), media_type="application/x-ndjson")
