"""Tests for CORS configuration and the startup secret check."""

import pytest

from api.main import allowed_origins, require_startup_configuration


def test_defaults_to_local_development_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert allowed_origins() == ["http://localhost:3000"]


def test_reads_a_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS", "https://app.example.com, https://admin.example.com "
    )
    assert allowed_origins() == ["https://app.example.com", "https://admin.example.com"]


@pytest.mark.parametrize("wildcard", ["*", "https://a.example.com,*", " * "])
def test_wildcard_origin_is_refused(monkeypatch: pytest.MonkeyPatch, wildcard: str) -> None:
    """A wildcard with credentials is rejected by browsers anyway, and would be a
    cross-origin read of every user's data if it were not."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", wildcard)

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        allowed_origins()


def test_startup_requires_the_auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        require_startup_configuration()


def test_startup_refuses_a_short_auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", "too-short")

    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        require_startup_configuration()


def test_startup_passes_with_valid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-secret-key-long-enough-for-hs256")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    require_startup_configuration()
