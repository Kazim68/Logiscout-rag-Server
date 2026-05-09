"""
LogiScout Response Pipeline — entry point.

Coordinates the multi-stage response flow:
    1. Intent detection (Gemini → Groq fallback chain)
    2. Vector retrieval from Qdrant
    3. Answer generation

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
from datetime import date, datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from .config import ResponsePipelineConfig
from .pipeline_steps import (
    AnswerGenerator,
    IntentDetector,
    LLMClient,
    LogEnrichmentStep,
    VectorRetrievalStep,
)

logger = logging.getLogger(__name__)


class CustomJSONEncoder(json.JSONEncoder):
    """JSON encoder that serializes datetime/date objects to ISO 8601 strings."""

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


class ResponsePipeline:
    """Coordinates the response pipeline stages."""

    def __init__(self, config: Optional[ResponsePipelineConfig] = None):
        self.config = config or ResponsePipelineConfig.from_env()
        self._qdrant_client = None

        # Shared LLM client so the Gemini module is initialized once.
        self._llm_client = LLMClient(self.config)
        self.intent_detector = IntentDetector(self.config, llm_client=self._llm_client)
        self.answer_generator = AnswerGenerator(self.config, llm_client=self._llm_client)
        self.vector_retrieval = VectorRetrievalStep(
            self.config,
            qdrant_client_getter=self.get_qdrant_client,
        )
        self.log_enrichment = LogEnrichmentStep(self.config)

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

    def collection_names_for(self, project_id: str) -> Dict[str, str]:
        """Resolve per-source Qdrant collection names for a given project."""
        return {
            "logs": f"{project_id}{self.config.logs_collection_suffix}",
            "commits": f"{project_id}{self.config.commits_collection_suffix}",
            "postmortem": f"{project_id}{self.config.postmortem_collection_suffix}",
        }

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
        collections = self.collection_names_for(project_id)
        logger.info(
            "Response pipeline stream start — project=%s, collection=%s",
            project_id, collections,
        )

        sources: list = []
        terminated_with_error = False

        try:
            yield self._frame("status", {"stage": "init", "collections": collections})

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
            yield self._frame("status", {"stage": "retrieval"})

            contexts = self.vector_retrieval.retrieve_contexts(
                project_id=project_id,
                user_prompt=user_prompt,
                needs_logs=intent_result.needs_logs,
                needs_commits=intent_result.needs_commits,
                needs_postmortem=intent_result.needs_postmortem,
            )
            sources = self._collect_sources(contexts)

            log_hits = contexts.get("log_context") or []
            if intent_result.needs_logs and log_hits:
                yield self._frame("status", {"stage": "log_enrichment"})
                self.log_enrichment.enrich(log_hits)

            yield self._frame("status", {"stage": "answer_generation"})

            answer_result = await self.answer_generator.generate(
                vague_context=vague_context,
                chat_context=chat_context,
                user_prompt=user_prompt,
                intent=intent_result.intent,
                contexts=contexts,
            )

            yield self._frame(
                "answer",
                {
                    "text": answer_result.text,
                    "provider": answer_result.provider,
                    "warning": answer_result.error,
                    **contexts,
                    "postmartems_context": contexts.get("postmortem_context"),
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
        return json.dumps({"event": event, "data": data}, cls=CustomJSONEncoder) + "\n"

    @staticmethod
    def _collect_sources(contexts: Dict[str, Optional[List[Dict[str, Any]]]]) -> List[str]:
        """Extract unique sources from all retrieval result buckets."""
        sources: List[str] = []
        seen = set()

        for items in contexts.values():
            for item in items or []:
                metadata = item.get("metadata") or {}
                source = (
                    metadata.get("html_url")
                    or metadata.get("commit_sha")
                    or metadata.get("source")
                    or metadata.get("file_path")
                    or metadata.get("log_file")
                )
                if source and source not in seen:
                    seen.add(source)
                    sources.append(source)

        return sources
