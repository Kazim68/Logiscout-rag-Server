"""Spark Fetcher Service: Reads flat log rows from OLAP, deduplicates via watermark, reassembles into RawTrace dicts."""

import json
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class SparkFetcherService:
    """Fetches flattened log rows from OLAP in batches, avoids duplicates, and reassembles nested traces."""

    def __init__(self, config):
        self.config = config

    # ── 1. Spark Session ──────────────────────────────────────────────

    def get_spark_session(self) -> "SparkSession":
        """Creates or reuses a SparkSession."""
        from pyspark.sql import SparkSession
        return (
            SparkSession.builder
            .appName("LogiScout-Pipeline")
            .config("spark.jars.packages", "org.postgresql:postgresql:42.7.1")
            .getOrCreate()
        )

    # ── 2. Watermark Persistence (dedup) ──────────────────────────────

    def load_watermark(self) -> str:
        """Reads the last-processed timestamp from the watermark file. Returns epoch zero on first run."""
        path = self.config.watermark_path
        if os.path.exists(path):
            with open(path, "r") as f:
                ts = f.read().strip()
                if ts:
                    return ts
        return "1970-01-01T00:00:00Z"

    def save_watermark(self, timestamp: str) -> None:
        """Persists the new high-watermark timestamp after a successful batch."""
        with open(self.config.watermark_path, "w") as f:
            f.write(timestamp)
        logger.info(f"Watermark updated to: {timestamp}")

    # ── 3. Query Builder ──────────────────────────────────────────────

    def build_fetch_query(self, watermark: str) -> str:
        """Constructs the SQL query to fetch rows newer than the watermark."""
        table = self.config.olap_table
        batch_size = self.config.fetch_batch_size
        return (
            f"(SELECT * FROM {table} "
            f"WHERE started_at > '{watermark}' "
            f"ORDER BY started_at ASC "
            f"LIMIT {batch_size}) AS batch"
        )

    # ── 4. Batch Fetcher ──────────────────────────────────────────────

    def fetch_batch(self, spark: "SparkSession", watermark: str) -> List[Dict[str, Any]]:
        """Executes the JDBC read against OLAP and returns rows as Python dicts."""
        query = self.build_fetch_query(watermark)

        df = (
            spark.read
            .format("jdbc")
            .option("url", self.config.olap_jdbc_url)
            .option("dbtable", query)
            .option("driver", self.config.olap_driver)
            .option("user", self.config.olap_user)
            .option("password", self.config.olap_password)
            .load()
        )

        rows = [row.asDict() for row in df.collect()]
        logger.info(f"Fetched {len(rows)} rows from OLAP")
        return rows

    # ── 5. Reassemble Flat Rows → Nested Traces ──────────────────────

    def reassemble_traces(self, flat_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Groups flat OLAP rows by correlation_id and rebuilds nested RawTrace dicts.

        Expected OLAP columns (snake_case):
            project_name, environment, correlation_id, component,
            started_at, ended_at, duration_ms,
            request_method, request_path, request_status_code,
            log_timestamp, log_level, log_message, log_component, log_meta
        """
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        trace_context: Dict[str, Dict[str, Any]] = {}

        for row in flat_rows:
            cid = row.get("correlation_id", "unknown")
            grouped[cid].append(row)

            # Capture trace-level fields from the first row per correlation_id
            if cid not in trace_context:
                request = None
                if row.get("request_method") or row.get("request_path"):
                    request = {
                        "method": row.get("request_method"),
                        "path": row.get("request_path"),
                        "statusCode": row.get("request_status_code"),
                    }

                trace_context[cid] = {
                    "projectName": row.get("project_name", ""),
                    "environment": row.get("environment", ""),
                    "correlationId": cid,
                    "component": row.get("component"),
                    "startedAt": row.get("started_at", ""),
                    "endedAt": row.get("ended_at"),
                    "durationMs": row.get("duration_ms"),
                    "request": request,
                }

        traces = []
        for cid, rows in grouped.items():
            trace = trace_context[cid]
            trace["logs"] = []
            for r in rows:
                # Parse log_meta from JSON string if stored as text
                meta = r.get("log_meta")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        meta = None

                trace["logs"].append({
                    "timestamp": r.get("log_timestamp", ""),
                    "level": r.get("log_level", "INFO"),
                    "message": r.get("log_message", ""),
                    "component": r.get("log_component", trace.get("component", "")),
                    "meta": meta,
                })
            traces.append(trace)

        logger.info(f"Reassembled {len(flat_rows)} flat rows into {len(traces)} traces")
        return traces

    # ── 6. Compute New Watermark ──────────────────────────────────────

    def compute_new_watermark(self, flat_rows: List[Dict[str, Any]], current_watermark: str) -> str:
        """Returns the latest started_at value from the batch, or the current watermark if empty."""
        if not flat_rows:
            return current_watermark
        # Rows are ordered ASC by started_at, so the last row has the latest timestamp
        return flat_rows[-1].get("started_at", current_watermark)
