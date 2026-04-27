"""
LogiScout Response Pipeline — entry point.

Coordinates the multi-stage response flow:
    1. Intent detection (Gemini → Groq fallback chain)
    2. (TODO) Retrieval from Qdrant
    3. (TODO) Answer generation

Usage:
    from app.services.response_pipeline import ResponsePipelineConfig, ResponsePipeline

    pipeline = ResponsePipeline(ResponsePipelineConfig.from_env())
    async for chunk in pipeline.run_stream(
        vague_context=..., chat_context=..., user_prompt=..., project_id=...,
    ):
        ...
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

from .config import ResponsePipelineConfig
from .pipeline_steps import IntentDetector, LLMClient

logger = logging.getLogger(__name__)


class ResponsePipeline:
    """Coordinates the response pipeline stages."""

    def __init__(self, config: Optional[ResponsePipelineConfig] = None):
        self.config = config or ResponsePipelineConfig.from_env()
        self._qdrant_client = None

        # Shared LLM client so the Gemini module is initialized once.
        self._llm_client = LLMClient(self.config)
        self.intent_detector = IntentDetector(self.config, llm_client=self._llm_client)

    # ── Connections ───────────────────────────────────────────────────

    def get_qdrant_client(self):
        """Lazily create and cache a Qdrant client."""
        if self._qdrant_client is None:
            from qdrant_client import QdrantClient

            kwargs: Dict[str, Any] = {"url": self.config.qdrant_url}
            if self.config.qdrant_api_key:
                kwargs["api_key"] = self.config.qdrant_api_key

            self._qdrant_client = QdrantClient(**kwargs)
            logger.info("Qdrant client connected: %s", self.config.qdrant_url)
        return self._qdrant_client

    def collection_name_for(self, project_id: str) -> str:
        """Resolve the Qdrant collection name for a given project."""
        return f"{project_id}{self.config.collection_suffix}"

    # ── Streaming Entry Point ─────────────────────────────────────────

    async def run_stream(
        self,
        vague_context: Any,
        chat_context: Any,
        user_prompt: str,
        project_id: str,
    ) -> AsyncIterator[str]:
        """
        Streaming entry point. Yields newline-delimited JSON chunks suitable
        for chunked HTTP transport.

        A terminal `done` event is always emitted, even if a stage errors,
        so clients can rely on it to close the stream cleanly.
        """
        collection = self.collection_name_for(project_id)
        logger.info(
            "Response pipeline stream start — project=%s, collection=%s",
            project_id, collection,
        )

        sources: list = []
        terminated_with_error = False

        try:
            yield self._frame("status", {"stage": "init", "collection": collection})

            # ── Stage 1: Intent Detection ─────────────────────────────
            yield self._frame("status", {"stage": "intent_detection"})

            intent_result = await self.intent_detector.detect(
                vague_context=vague_context,
                chat_context=chat_context,
                user_prompt=user_prompt,
            )

            if intent_result.provider == "unavailable":
                terminated_with_error = True
                yield self._frame(
                    "error",
                    {
                        "stage": "intent_detection",
                        "code": "llm_unavailable",
                        "message": intent_result.error
                        or "LLM service not available — please try again later.",
                    },
                )
                return

            yield self._frame("intent", intent_result.to_dict())

            # ── Stage 2+: Retrieval & Generation (placeholders) ───────
            yield self._frame(
                "answer",
                {
                    "text": (
                        f"[scaffold] Detected intent: {intent_result.intent} "
                        f"(confidence={intent_result.confidence:.2f}). "
                        f"needs_logs={intent_result.needs_logs}, "
                        f"needs_commits={intent_result.needs_commits}, "
                        f"needs_postmortem={intent_result.needs_postmortem}. "
                        "Retrieval and generation stages coming next."
                    ),
                },
            )

        except Exception as e:
            terminated_with_error = True
            logger.error("Response pipeline crashed: %s", e, exc_info=True)
            yield self._frame(
                "error",
                {
                    "stage": "pipeline",
                    "code": "internal_error",
                    "message": f"Internal pipeline error: {e}",
                },
            )

        finally:
            # Guaranteed terminal event so clients always see the stream close.
            yield self._frame(
                "done",
                {
                    "ok": not terminated_with_error,
                    "sources": sources,
                },
            )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _frame(event: str, data: Dict[str, Any]) -> str:
        """Serialize a single chunk as a newline-delimited JSON event."""
        return json.dumps({"event": event, "data": data}) + "\n"
