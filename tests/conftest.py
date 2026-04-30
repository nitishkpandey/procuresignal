"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_article() -> dict:
    """Sample article for testing."""
    return {
        "title": "Test Article",
        "description": "Test description",
        "source": "test-source",
        "url": "https://example.com/article",
        "published_at": "2024-01-01T00:00:00Z",
    }
