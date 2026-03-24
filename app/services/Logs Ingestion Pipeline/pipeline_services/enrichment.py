"""Enrichment Layer: Error extraction, fingerprinting, and severity scoring."""

import re
import hashlib
from typing import Optional, Tuple
from dataclasses import dataclass
from .models import LogLevels
from .transformation import TransformedLog


@dataclass
class EnrichedLog(TransformedLog):
    """TransformedLog extended with enrichment outputs."""
    error_type: Optional[str] = None
    stack_trace_snippet: Optional[str] = None
    fingerprint: Optional[str] = None
    severity_score: int = 0


class EnrichmentService:
    """Decomposes log enrichment into independent, single-responsibility functions."""

    # ── 1. Message Normalization ──────────────────────────────────────

    def normalize_message(self, message: str) -> str:
        """Strips dynamic values (UUIDs, IPs, hex addresses, numbers) to create a stable template."""
        normalized = re.sub(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', '<UUID>', message)
        normalized = re.sub(r'0x[0-9a-fA-F]+', '<HEX_ADDR>', normalized)
        normalized = re.sub(r'\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b', '<IP>', normalized)
        normalized = re.sub(r'\b\d+\b', '<NUM>', normalized)
        return normalized

    # ── 2. Error Type Extraction ──────────────────────────────────────

    def extract_error_type(self, message: str, meta: Optional[dict] = None) -> Optional[str]:
        """Extracts the error type/class name from the log message or meta."""
        # Strategy 1: CamelCase error naming (e.g. ConnectionTimeout, ValueError)
        match = re.search(r'\b([A-Z][A-Za-z0-9]*(?:Error|Exception|Timeout|Failure|Refused|Denied|Overflow|Violation))\b', message)
        if match:
            return match.group(1)

        # Strategy 2: "ErrorName: description" pattern
        if ":" in message:
            candidate = message.split(":")[0].strip()
            if " " not in candidate and len(candidate) <= 50:
                return candidate

        # Strategy 3: Fallback to meta field
        if meta and 'error_type' in meta:
            return str(meta['error_type'])

        return None

    # ── 3. Stack Trace Extraction ─────────────────────────────────────

    def extract_stack_trace(self, message: str) -> Optional[str]:
        """Extracts a stack trace snippet from the log message."""
        # Python-style: "file.py:88 in acquire_connection()"
        match = re.search(r'([a-zA-Z0-9_\-]+\.py:\d+\s+in\s+[a-zA-Z0-9_]+\(\))', message)
        if match:
            return match.group(1)

        # Generic: "at module.function (file:line)"
        match = re.search(r'(at\s+[\w.]+\s*\([\w./\\:]+:\d+\))', message)
        if match:
            return match.group(1)

        return None

    # ── 4. Deterministic Fingerprinting ───────────────────────────────

    def compute_fingerprint(self, service: str, error_type: Optional[str], normalized_message: str) -> str:
        """Creates a deterministic fingerprint from normalized content for error grouping."""
        err_type_str = error_type or "General"
        raw = f"{service}|{err_type_str}|{normalized_message}".encode('utf-8')
        digest = hashlib.md5(raw).hexdigest()

        prefix = service[:3].upper().replace("-", "") if len(service) >= 3 else "LOG"
        return f"{prefix}-{digest[:8].upper()}"

    # ── 5. Severity Scoring ───────────────────────────────────────────

    def compute_severity_score(self, level: LogLevels, error_type: Optional[str], message: str) -> int:
        """Assigns a numeric severity score (1-10) based on level, error type, and message keywords."""
        # Base score from log level
        base = {
            LogLevels.DEBUG: 1,
            LogLevels.INFO:  2,
            LogLevels.WARN:  4,
            LogLevels.ERROR: 7,
            LogLevels.FATAL: 9,
        }.get(level, 2)

        # Boost for critical error patterns
        critical_keywords = ['timeout', 'deadlock', 'oom', 'out of memory', 'crash',
                             'fatal', 'panic', 'segfault', 'corruption', 'unreachable']
        msg_lower = message.lower()
        if any(kw in msg_lower for kw in critical_keywords):
            base = min(base + 2, 10)

        # Boost if an explicit error_type was detected
        if error_type and level in (LogLevels.ERROR, LogLevels.FATAL):
            base = min(base + 1, 10)

        return base

    # ── 6. Orchestrator ───────────────────────────────────────────────

    def enrich_log(self, transformed_log: TransformedLog) -> EnrichedLog:
        """Orchestrates all enrichment steps for a single log entry."""
        log = transformed_log.log_entry
        error_type = None
        stack_trace_snippet = None
        fingerprint = None
        severity_score = 0

        # Always compute severity
        normalized = self.normalize_message(log.message)
        severity_score = self.compute_severity_score(log.level, None, log.message)

        # Full enrichment for non-info/debug logs
        if log.level in (LogLevels.ERROR, LogLevels.FATAL, LogLevels.WARN):
            error_type = self.extract_error_type(log.message, log.meta)
            stack_trace_snippet = self.extract_stack_trace(log.message)
            fingerprint = self.compute_fingerprint(transformed_log.service, error_type, normalized)
            # Re-score with error_type knowledge
            severity_score = self.compute_severity_score(log.level, error_type, log.message)

        return EnrichedLog(
            service=transformed_log.service,
            environment=transformed_log.environment,
            ls_ts=transformed_log.ls_ts,
            ls_ts_unix=transformed_log.ls_ts_unix,
            request_method=transformed_log.request_method,
            request_path=transformed_log.request_path,
            request_status_code=transformed_log.request_status_code,
            log_entry=log,
            trace=transformed_log.trace,
            error_type=error_type,
            stack_trace_snippet=stack_trace_snippet,
            fingerprint=fingerprint,
            severity_score=severity_score,
        )

    def enrich_logs(self, transformed_logs: list[TransformedLog]) -> list[EnrichedLog]:
        """Enriches a batch of transformed logs."""
        return [self.enrich_log(t) for t in transformed_logs]
