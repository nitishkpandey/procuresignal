"""Pytest configuration and fixtures."""

import pytest
from procuresignal.models import Role

from api.dependencies import AuthenticatedUser
from api.main import app
from api.rate_limit import login_limiter, registration_limiter


def fixed_identity(public_id: str, *, role: Role = Role.OWNER) -> AuthenticatedUser:
    """A stand-in identity for tests that exercise behaviour rather than authentication.

    Routes take their user from `get_current_user`, so overriding that dependency lets a
    functional test keep asserting on feed ranking, translation, or filters without
    minting real tokens. Token handling, rotation, and cross-tenant access are covered
    for real in test_auth_api.py and test_tenant_isolation.py.
    """

    return AuthenticatedUser(
        id=1,
        public_id=public_id,
        email=f"{public_id}@example.test",
        organization_id=1,
        organization_public_id="org-test",
        role=role,
    )


@pytest.fixture(autouse=True)
def _auth_secret(monkeypatch: pytest.MonkeyPatch):
    """The app refuses to start without a signing secret, so every test gets one.

    Set through monkeypatch so a test checking the missing-secret behaviour can
    still delete it.
    """

    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-that-is-long-enough-32")


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Throttles are process-wide singletons, so one test's attempts would
    otherwise count against the next one."""

    for limiter in (login_limiter, registration_limiter):
        limiter.reset()
    yield


@pytest.fixture(autouse=True)
def _reset_dependency_overrides():
    """Clear FastAPI dependency overrides after every test.

    `app` is module-level and shared, so a fixture that installs an override and forgets
    to remove it silently authenticates unrelated tests in other files. That is a
    confusing failure to chase down, so it is prevented here rather than remembered.
    """

    yield
    app.dependency_overrides.clear()


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
