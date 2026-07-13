"""Main FastAPI application."""

from contextlib import asynccontextmanager
from os import getenv
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from procuresignal.config.database import close_db, init_db
from starlette.middleware.gzip import GZipMiddleware

from api.routers import articles, chat, currency, feed, health, preferences, risk_events, signals
from api.scheduler import create_scheduler, scheduler_enabled


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = getenv("DATABASE_URL")
    if database_url:
        await init_db(database_url)

    scheduler = None
    if scheduler_enabled():
        scheduler = create_scheduler()
        scheduler.start()

    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)

        await close_db()


app = FastAPI(
    title="ProcureSignal API",
    description="AI-powered procurement news aggregation and personalization",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(health.router)
app.include_router(feed.router)
app.include_router(risk_events.router)
app.include_router(preferences.router)
app.include_router(chat.router)
app.include_router(articles.router)
app.include_router(signals.router)
app.include_router(currency.router)


@app.get("/health")
async def root_health() -> dict[str, str]:
    """Legacy health check endpoint."""

    return {"status": "healthy", "service": "api"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""

    return {
        "service": "ProcureSignal API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
