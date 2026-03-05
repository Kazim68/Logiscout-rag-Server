"""
Application-wide constants.
"""

# ── Collection names (MongoDB) ──────────────────────────────
COLLECTION_PROCESSED_LOGS = "processed_logs"
COLLECTION_INGESTION_JOBS = "ingestion_jobs"

# ── Job statuses ────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
