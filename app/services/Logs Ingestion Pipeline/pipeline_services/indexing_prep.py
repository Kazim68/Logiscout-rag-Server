"""Indexing Prep Layer: Builds vector-ready documents with semantic text and filterable metadata."""

import uuid
from typing import List, Dict, Any
from .models import EnrichedDocument, EnrichedPayload
from .enrichment import EnrichedLog


class IndexingPrepService:
    """Shapes enriched logs into final EnrichedDocuments ready for vectorDB storage."""

    # ── 1. Semantic Text Builder ──────────────────────────────────────

    def build_semantic_text(self, el: EnrichedLog) -> str:
        """
        Constructs a natural-language summary optimized for embedding.
        This is the string that will be vectorized for semantic search by the RAG retriever.
        """
        parts = []

        # Level + Error Type headline
        level = el.log_entry.level.value
        if el.error_type:
            parts.append(f"[{level}] {el.error_type} in {el.service}")
        else:
            parts.append(f"[{level}] Log from {el.service}")

        # Project + Environment context
        parts.append(f"(project: {el.trace.projectName}, environment: {el.environment})")

        # Request context if available
        if el.request_method and el.request_path:
            req = f"{el.request_method} {el.request_path}"
            if el.request_status_code:
                req += f" -> {el.request_status_code}"
            if el.trace.durationMs is not None:
                req += f", duration: {el.trace.durationMs}ms"
            parts.append(f"[request: {req}]")
        elif el.trace.durationMs is not None:
            parts.append(f"[duration: {el.trace.durationMs}ms]")

        # Core message
        parts.append(f": {el.log_entry.message}")

        # Stack trace if available
        if el.stack_trace_snippet:
            parts.append(f"| trace: {el.stack_trace_snippet}")

        # Surface structured meta fields for semantic searchability
        if el.log_entry.meta:
            meta_parts = [f"{k}={v}" for k, v in el.log_entry.meta.items()
                          if k != "error_type" and v is not None]
            if meta_parts:
                parts.append(f"| context: {', '.join(meta_parts)}")

        return " ".join(parts)

    # ── 2. Vector Metadata Builder ────────────────────────────────────

    def build_vector_metadata(self, el: EnrichedLog) -> Dict[str, Any]:
        """
        Builds a flat metadata dict for Qdrant/vectorDB payload.
        These fields are used for filtered search (e.g., filter by env, service, level).
        """
        meta: Dict[str, Any] = {
            "project_name": el.trace.projectName,
            "service": el.service,
            "environment": el.environment,
            "level": el.log_entry.level.value,
            "severity_score": el.severity_score,
            "correlation_id": el.trace.correlationId,
            "timestamp_unix": el.ls_ts_unix,
        }

        if el.trace.durationMs is not None:
            meta["duration_ms"] = el.trace.durationMs
        if el.fingerprint:
            meta["fingerprint"] = el.fingerprint
        if el.error_type:
            meta["error_type"] = el.error_type
        if el.request_method:
            meta["request_method"] = el.request_method
        if el.request_path:
            meta["request_path"] = el.request_path
        if el.request_status_code is not None:
            meta["request_status_code"] = el.request_status_code

        return meta

    # ── 3. Single Document Assembly ───────────────────────────────────

    def prepare_document(self, el: EnrichedLog) -> EnrichedDocument:
        """Assembles one final EnrichedDocument from an enriched log entry."""
        payload = EnrichedPayload(
            level=el.log_entry.level.value,
            service=el.service,
            environment=el.environment,
            message=el.log_entry.message,
            error_type=el.error_type,
            stack_trace_snippet=el.stack_trace_snippet,
            fingerprint=el.fingerprint,
            severity_score=el.severity_score,
            request_method=el.request_method,
            request_path=el.request_path,
            request_status_code=el.request_status_code,
        )

        return EnrichedDocument(
            ls_id=f"log-{uuid.uuid4().hex[:8]}",
            ls_ts=el.ls_ts,
            ls_ts_unix=el.ls_ts_unix,
            ls_cid=el.trace.correlationId,
            payload=payload,
            semantic_text=self.build_semantic_text(el),
            vector_metadata=self.build_vector_metadata(el),
        )

    # ── 4. Batch Processor ────────────────────────────────────────────

    def prepare_documents(self, enriched_logs: List[EnrichedLog]) -> List[EnrichedDocument]:
        """Prepares a batch of enriched logs into vector-ready documents."""
        return [self.prepare_document(el) for el in enriched_logs]
