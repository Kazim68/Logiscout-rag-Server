"""
MongoDB connection using Motor (async driver).

Despite the folder name 'postgres', this project uses MongoDB for
the primary data store (processed logs from the LLM pipeline).
The folder acts as the "metadata DB" layer in the architecture.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.settings import settings
import logging

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def init_db() -> None:
    """Open the Motor client and warm-up a server ping."""
    global _client, _db
    _client = AsyncIOMotorClient(settings.MONGODB_URL)
    _db = _client[settings.MONGODB_DB_NAME]
    # Quick connectivity check
    await _client.admin.command("ping")
    logger.info("MongoDB connected → %s", settings.MONGODB_DB_NAME)


async def close_db() -> None:
    """Close the Motor client."""
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed")


async def get_db() -> AsyncIOMotorDatabase:
    """Return the database handle (available after startup)."""
    if _db is None:
        raise RuntimeError("Database not initialised – call init_db() first")
    return _db
