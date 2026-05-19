"""Health check endpoints."""

from datetime import datetime

from fastapi import APIRouter
from procuresignal.config import database
from sqlalchemy import text

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for the REST API."""

    db_status = "disconnected"
    error_message = None

    db_config = database.db_config
    if db_config is not None and db_config.session_maker is not None:
        try:
            async with db_config.session_maker() as session:
                await session.execute(text("SELECT 1"))
            db_status = "connected"
        except Exception as exc:  # pragma: no cover - runtime connectivity path
            db_status = "error"
            error_message = str(exc)

    payload = {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "service": "api",
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status,
    }
    if error_message:
        payload["error"] = error_message

    return payload
