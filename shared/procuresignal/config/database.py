"""Database configuration and connection management."""

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

WORKER_DATABASE_URL = "postgresql+asyncpg://procuresignal:procuresignal@postgres:5432/procuresignal"


class DatabaseConfig:
    """Database configuration and connection management."""

    def __init__(self, database_url: str):
        """Initialize database config.

        Args:
            database_url: PostgreSQL async connection string
                Example: postgresql+asyncpg://user:pass@localhost/dbname
        """
        self.database_url = database_url
        self.engine = None
        self.session_maker = None

    async def initialize(self) -> None:
        """Initialize async engine and session factory."""
        self.engine = create_async_engine(
            self.database_url,
            echo=False,  # Set to True for SQL query debugging
            future=True,
            poolclass=NullPool,
            connect_args={
                "timeout": 10,
                "command_timeout": 10,
            },
        )

        self.session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    async def close(self) -> None:
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()


# Global instance
db_config: "DatabaseConfig | None" = None


@asynccontextmanager
async def session_scope(database_url: str | None = None) -> AsyncIterator[AsyncSession]:
    """One-off session against a per-call engine.

    For workers and scripts that run without the API's long-lived pool. Falls back
    to DATABASE_URL, then the in-cluster worker default.
    """
    url = database_url or os.getenv("DATABASE_URL", WORKER_DATABASE_URL)
    engine = create_async_engine(url, future=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def init_db(database_url: str) -> None:
    """Initialize database on app startup."""
    global db_config
    db_config = DatabaseConfig(database_url)
    await db_config.initialize()


async def close_db() -> None:
    """Close database on app shutdown."""
    if db_config:
        await db_config.close()
