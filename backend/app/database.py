"""Database configuration: async engine, session factory, and retry logic."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

logger = logging.getLogger(__name__)

DATABASE_URL = settings.database_url

# pool_pre_ping recycles connections that the database closed while idle
# (e.g. after a restart), avoiding stale-connection errors on the next query.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        yield session


async def wait_for_db(max_retries: int = 5, retry_interval: float = 3.0) -> None:
    """Wait for the database to become reachable.

    Retries up to *max_retries* times with *retry_interval* seconds between
    attempts. Raises RuntimeError if the database remains unreachable.

    Args:
        max_retries: Maximum number of connection attempts.
        retry_interval: Seconds to wait between retries.

    Raises:
        RuntimeError: If the database is not reachable after all retries.

    """
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connection established (attempt %d).", attempt)
            return
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    "Database unreachable (attempt %d/%d): %s. "
                    "Retrying in %.0f seconds...",
                    attempt,
                    max_retries,
                    str(e),
                    retry_interval,
                )
                await asyncio.sleep(retry_interval)
            else:
                logger.error(
                    "Database unreachable after %d attempts. "
                    "Check DATABASE_URL and database availability.",
                    max_retries,
                )
                raise RuntimeError(
                    f"Database unreachable after {max_retries} attempts: {e}"
                ) from e
