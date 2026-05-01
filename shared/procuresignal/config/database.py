"""Database configuration and connection management."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


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

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get async database session."""
        if not self.session_maker:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        async with self.session_maker() as session:
            yield session


# Global instance
db_config: "DatabaseConfig | None" = None


async def init_db(database_url: str) -> None:
    """Initialize database on app startup."""
    global db_config
    db_config = DatabaseConfig(database_url)
    await db_config.initialize()


async def close_db() -> None:
    """Close database on app shutdown."""
    if db_config:
        await db_config.close()
