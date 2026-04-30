"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient

from api.main import app


@pytest.mark.asyncio
async def test_health_check() -> None:
    """Test health check endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_root_endpoint() -> None:
    """Test root endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "ProcureSignal API" in response.json()["message"]
