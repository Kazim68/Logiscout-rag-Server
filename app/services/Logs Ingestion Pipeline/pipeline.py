"""
LogiScout Log Ingestion Pipeline — Orchestrator.

Usage (manual / server integration):
    from pipeline import LogProcessingPipeline
    pipeline = LogProcessingPipeline(config)
    documents = pipeline.process_trace(raw_trace_dict)

Usage (scheduled PySpark batch mode):
    from pipeline import LogProcessingPipeline
    from config import Config
    pipeline = LogProcessingPipeline(Config.from_env())
    pipeline.run()
"""

import time
import logging
from typing import List, Dict, Any

from pipeline_services import (
    IngestionService,
    TransformationService,
    EnrichmentService,
    IndexingPrepService,
    EnrichedDocument,
)
from pipeline_services.spark_fetcher import SparkFetcherService
from pipeline_services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


class LogProcessingPipeline:
    """
    Entry point for the log processing pipeline.

    Coordinates:  Spark Fetch → Ingestion → Transformation → Enrichment → Indexing Prep → VectorDB Store
    """

    def __init__(self, config=None):
        self.config = config
        self.ingestion = IngestionService()
        self.transformation = TransformationService()
        self.enrichment = EnrichmentService()
        self.indexing_prep = IndexingPrepService()
        self.vector_store = VectorStoreService(config) if config else None

    # ── Single-Trace Entry Point (for server/developer use) ───────────

    def process_trace(self, raw_trace_dict: Dict[str, Any]) -> List[EnrichedDocument]:
        """
        Accepts a single raw trace dict, returns vector-ready documents.
        If config was provided, also stores documents in VectorDB.
        """
        # 1. Ingestion: validate
        validated_trace = self.ingestion.validate_trace(raw_trace_dict)

        # 2. Transformation: flatten + normalize
        transformed_logs = self.transformation.transform_trace(validated_trace)

        # 3. Enrichment: error extraction, fingerprinting, severity
        enriched_logs = self.enrichment.enrich_logs(transformed_logs)

        # 4. Indexing Prep: semantic text + vector metadata
        documents = self.indexing_prep.prepare_documents(enriched_logs)

        # 5. Vector Store: embed + upsert to Qdrant
        if self.vector_store:
            self.vector_store.upsert_documents(documents)

        return documents

    # ── Batch Entry Point (PySpark scheduled mode) ────────────────────

    def process_batch(self, traces: List[Dict[str, Any]]) -> List[EnrichedDocument]:
        """Processes multiple reassembled traces and returns all documents."""
        all_docs = []
        for trace in traces:
            try:
                docs = self.process_trace(trace)
                all_docs.extend(docs)
            except Exception as e:
                cid = trace.get("correlationId", "unknown")
                logger.error(f"Failed to process trace {cid}: {e}")
        return all_docs

    def run(self) -> None:
        """
        Starts the scheduled pipeline loop.
        Fetches batches from OLAP via PySpark, processes, and stores in VectorDB.
        """
        if not self.config:
            raise ValueError("Config is required for scheduled mode. Pass config to __init__.")

        fetcher = SparkFetcherService(self.config)
        spark = fetcher.get_spark_session()
        interval_sec = self.config.fetch_interval_minutes * 60

        logger.info(
            f"Pipeline scheduler started — fetching every {self.config.fetch_interval_minutes} min "
            f"(batch size: {self.config.fetch_batch_size})"
        )

        while True:
            try:
                watermark = fetcher.load_watermark()
                logger.info(f"Current watermark: {watermark}")

                flat_rows = fetcher.fetch_batch(spark, watermark)

                if not flat_rows:
                    logger.info("No new rows. Sleeping.")
                else:
                    traces = fetcher.reassemble_traces(flat_rows)
                    documents = self.process_batch(traces)
                    logger.info(f"Produced and stored {len(documents)} documents")

                    new_watermark = fetcher.compute_new_watermark(flat_rows, watermark)
                    fetcher.save_watermark(new_watermark)

            except Exception as e:
                logger.error(f"Batch cycle failed: {e}", exc_info=True)

            time.sleep(interval_sec)
