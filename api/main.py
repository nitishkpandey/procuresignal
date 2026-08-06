"""Main FastAPI application."""

from contextlib import asynccontextmanager
from os import getenv
from typing import AsyncIterator

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from procuresignal.auth.tokens import require_auth_secret
from procuresignal.config.database import close_db, init_db
from starlette.middleware.gzip import GZipMiddleware

from api.metrics import METRICS_PATH, MetricsMiddleware, metrics_response
from api.routers import (
    articles,
    auth,
    chat,
    currency,
    feed,
    health,
    preferences,
    risk_events,
    signals,
    suppliers,
)
from api.scheduler import create_scheduler, scheduler_enabled

DEFAULT_ALLOWED_ORIGIN = "http://localhost:3000"


def allowed_origins() -> list[str]:
    """Browser origins permitted to call this API with credentials.

    A wildcard is refused outright. Browsers already reject `*` alongside
    `allow_credentials`, so it would silently break the refresh cookie, and if it
    did work it would let any site on the internet read every user's data.
    """

    raw = getenv("CORS_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGIN)
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if any(origin == "*" for origin in origins):
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS must name explicit origins; '*' cannot be used "
            "with credentialed requests"
        )
    return origins or [DEFAULT_ALLOWED_ORIGIN]


def require_startup_configuration() -> None:
    """Fail fast on a misconfigured deployment.

    Checked at import rather than at first sign-in, so a bad deployment cannot come
    up healthy and then reject every user.
    """

    require_auth_secret()
    allowed_origins()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    require_startup_configuration()

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
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(MetricsMiddleware)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(feed.router)
app.include_router(risk_events.router)
app.include_router(preferences.router)
app.include_router(chat.router)
app.include_router(articles.router)
app.include_router(signals.router)
app.include_router(currency.router)
app.include_router(suppliers.router)


@app.get(METRICS_PATH, include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape target, configured in prometheus.yml since before it existed."""

    return metrics_response()


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
