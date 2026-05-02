"""Enriches log-vector hits with related logs from ClickHouse.

For each log vector retrieved from Qdrant we look up rows in
`{database}.{table}` matching the vector's `correlation_id` and attach
them under `metadata.related_logs`. The metadata dict is serialized into
the LLM prompt by the answer generator, so no prompt changes are needed.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ..config import ResponsePipelineConfig

logger = logging.getLogger(__name__)


class LogEnrichmentStep:
    """Adds `metadata.related_logs` to log-vector hits via ClickHouse."""

    def __init__(self, config: ResponsePipelineConfig) -> None:
        self.config = config
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        if self._client is None:
            import clickhouse_connect

            self._client = clickhouse_connect.get_client(
                host=self.config.clickhouse_host,
                port=self.config.clickhouse_port,
                username=self.config.clickhouse_user,
                password=self.config.clickhouse_password,
                database=self.config.clickhouse_database,
            )
            logger.info(
                "ClickHouse client connected: %s:%s/%s",
                self.config.clickhouse_host,
                self.config.clickhouse_port,
                self.config.clickhouse_database,
            )
        return self._client

    def enrich(self, log_hits: List[Dict[str, Any]]) -> None:
        """Mutate `log_hits` in place, attaching `metadata.related_logs`."""
        if not log_hits:
            return

        correlation_ids: List[str] = []
        seen: set = set()
        for hit in log_hits:
            metadata = hit.get("metadata") or {}
            corr_id = metadata.get("correlation_id")
            if corr_id and corr_id not in seen:
                seen.add(corr_id)
                correlation_ids.append(corr_id)

        if not correlation_ids:
            logger.info("LogEnrichmentStep: no correlation_ids on log hits; skipping")
            return

        try:
            grouped = self._fetch_related_logs(correlation_ids)
        except Exception as exc:
            logger.error(
                "ClickHouse related-logs fetch failed for %d correlation_ids: %s",
                len(correlation_ids), exc, exc_info=True,
            )
            return

        for hit in log_hits:
            metadata = hit.setdefault("metadata", {})
            corr_id = metadata.get("correlation_id")
            metadata["related_logs"] = grouped.get(corr_id, []) if corr_id else []

        logger.info(
            "LogEnrichmentStep: enriched %d hit(s) across %d correlation_id(s)",
            len(log_hits), len(correlation_ids),
        )

    def _fetch_related_logs(self, correlation_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Run a single batched ClickHouse query and group rows by correlationId."""
        client = self._get_client()
        table = f"{self.config.clickhouse_database}.{self.config.clickhouse_logs_table}"
        limit = self.config.clickhouse_related_logs_limit

        # `LIMIT N BY correlationId` returns up to N rows per group.
        # Parameter binding (parameters=) prevents injection via correlation_ids.
        query = (
            f"SELECT * FROM {table} "
            f"WHERE correlationId IN %(ids)s "
            f"ORDER BY correlationId, timestamp DESC "
            f"LIMIT {int(limit)} BY correlationId"
        )

        result = client.query(query, parameters={"ids": correlation_ids})
        rows = result.named_results()

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            corr_id = row.get("correlationId")
            if corr_id is None:
                continue
            grouped.setdefault(corr_id, []).append(dict(row))
        return grouped
