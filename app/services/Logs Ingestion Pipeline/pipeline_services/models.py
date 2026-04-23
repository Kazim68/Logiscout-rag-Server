"""Pydantic models for the LogiScout log processing pipeline."""

from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel


# ============================================ #
#  Input Schemas (from application traces)     #
# ============================================ #

class LogLevels(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    DEBUG = "DEBUG"
    FATAL = "FATAL"


class RequestInfo(BaseModel):
    method: Optional[str] = None
    path: Optional[str] = None
    statusCode: Optional[int] = None


class RawLogEntry(BaseModel):
    timestamp: str
    level: LogLevels
    message: str
    meta: Optional[Dict[str, Any]] = None
    component: str


class RawTrace(BaseModel):
    projectName: str
    environment: str
    correlationId: str
    component: Optional[str] = None
    startedAt: str
    endedAt: Optional[str] = None
    durationMs: Optional[int] = None
    request: Optional[RequestInfo] = None
    logs: List[RawLogEntry]


# ============================================ #
#  Output Schemas (vector-ready documents)     #
# ============================================ #

class EnrichedPayload(BaseModel):
    """Core enriched fields for a single log entry."""
    level: str
    service: str
    environment: str
    message: str

    # Error info (extracted from message, not same as level)
    error_type: Optional[str] = None
    stack_trace_snippet: Optional[str] = None

    # Deterministic grouping key
    fingerprint: Optional[str] = None

    # Numeric severity for ranking/filtering (1-10)
    severity_score: int = 0

    # Request context if available
    request_method: Optional[str] = None
    request_path: Optional[str] = None
    request_status_code: Optional[int] = None


class EnrichedDocument(BaseModel):
    """Final vector-ready document. Single output unit of the pipeline."""
    ls_id: str
    ls_ts: str
    ls_ts_unix: int
    ls_cid: str
    payload: EnrichedPayload

    # Pre-built natural-language string optimized for embedding
    semantic_text: str

    # Flat metadata dict for Qdrant/vectorDB filterable payload
    vector_metadata: Dict[str, Any]
