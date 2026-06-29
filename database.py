"""
Dhandho AI — database.py
Async MongoDB connection management using the Motor driver.
"""

import os
import logging
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (populated during lifespan startup)
# ---------------------------------------------------------------------------
_client: Optional[AsyncIOMotorClient] = None
db: Optional[AsyncIOMotorDatabase] = None

# Named collection references (populated after `connect_to_db` is called)
chat_sessions = None   # Stores per-session conversation history
reports = None         # Stores compiled AI analysis reports
users_chat_history = None  # Stores user-specific chat history for persistence


# ---------------------------------------------------------------------------
# Connection helpers (called from main.py lifespan)
# ---------------------------------------------------------------------------
async def connect_to_db() -> None:
    """
    Opens the Motor connection pool and initialises the module-level
    `db` and collection references.

    Reads MONGODB_URI from the environment (falls back to localhost).
    """
    global _client, db, chat_sessions, reports, users_chat_history

    mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")

    try:
        _client = AsyncIOMotorClient(
            mongo_uri,
            serverSelectionTimeoutMS=5_000,   # fail fast if unreachable
        )
        # Ping the deployment to confirm the connection works
        await _client.admin.command("ping")

        db = _client.dhandho_ai

        # Materialise collection references
        chat_sessions = db.chat_sessions
        reports = db.reports
        users_chat_history = db.users_chat_history

        logger.info("✅  Connected to MongoDB — database: dhandho_ai")

    except Exception as exc:
        logger.critical("❌  Failed to connect to MongoDB: %s", exc)
        raise


async def close_db_connection() -> None:
    """Gracefully closes the Motor connection pool."""
    global _client

    if _client is not None:
        _client.close()
        logger.info("🔌  MongoDB connection closed.")


# ---------------------------------------------------------------------------
# Utility — expose a ready-to-use db handle for imports
# ---------------------------------------------------------------------------
def get_db() -> AsyncIOMotorDatabase:
    """
    Returns the active database instance.

    Raises RuntimeError if called before `connect_to_db()` has completed
    (i.e. before the FastAPI lifespan has started).
    """
    if db is None:
        raise RuntimeError(
            "Database not initialised. "
            "Ensure `connect_to_db()` is awaited during app startup."
        )
    return db
