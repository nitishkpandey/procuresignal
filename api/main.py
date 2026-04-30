"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="ProcureSignal API", description="AI-powered procurement intelligence", version="0.1.0"
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration."""
    return {"status": "healthy", "service": "api"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "ProcureSignal API v0.1.0 — Phase 0 scaffold"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
