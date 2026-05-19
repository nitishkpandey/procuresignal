"""API dependency helpers."""

from collections.abc import AsyncGenerator

from fastapi import HTTPException, status
from procuresignal.config import database
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for API handlers."""

    db_config = database.db_config
    if db_config is None or db_config.session_maker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    async with db_config.session_maker() as session:
        yield session
