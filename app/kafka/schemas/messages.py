"""
Kafka message schemas (Pydantic models for serialization).
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class IngestionMessage(BaseModel):
    job_id: str
    source: str
    payload: dict
    metadata: Optional[dict] = None
    created_at: datetime
