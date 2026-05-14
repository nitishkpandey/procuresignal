"""FastAPI application entry point."""

from os import getenv

from fastapi import FastAPI

from api.api.routers.signals import router as signals_router
from shared.procuresignal.config.database import close_db, init_db

app = FastAPI(
    title="ProcureSignal API",
    description="AI-powered procurement intelligence",
    version="0.1.0",
)


@app.on_event("startup")
async def startup_event():
    database_url = getenv("DATABASE_URL")
    if database_url:
        await init_db(database_url)
        app.include_router(signals_router)


@app.on_event("shutdown")
async def shutdown_event():
    await close_db()


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration."""
    return {"status": "healthy", "service": "api"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "ProcureSignal API v0.1.0 — Phase 4 signals"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
