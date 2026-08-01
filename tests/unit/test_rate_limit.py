"""Tests for the failed-attempt throttle."""

import pytest

from api.rate_limit import RateLimiter


def test_allows_attempts_up_to_the_limit() -> None:
    limiter = RateLimiter(max_attempts=3, window_seconds=60)

    for _ in range(3):
        assert limiter.check("ip:email") is None
        limiter.record("ip:email")

    assert limiter.check("ip:email") is not None


def test_only_recorded_attempts_count() -> None:
    """Successful sign-ins are never recorded, so normal use is never throttled."""
    limiter = RateLimiter(max_attempts=2, window_seconds=60)

    for _ in range(50):
        assert limiter.check("ip:email") is None

    assert limiter.check("ip:email") is None


def test_keys_are_throttled_independently() -> None:
    limiter = RateLimiter(max_attempts=1, window_seconds=60)

    limiter.record("victim")
    assert limiter.check("victim") is not None
    assert limiter.check("someone-else") is None


def test_window_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    limiter = RateLimiter(max_attempts=2, window_seconds=60, clock=lambda: now[0])

    limiter.record("k")
    limiter.record("k")
    assert limiter.check("k") is not None

    now[0] += 61
    assert limiter.check("k") is None


def test_retry_after_counts_down() -> None:
    now = [1000.0]
    limiter = RateLimiter(max_attempts=1, window_seconds=60, clock=lambda: now[0])

    limiter.record("k")
    assert limiter.check("k") == 60

    now[0] += 30
    assert limiter.check("k") == 30


def test_expired_keys_are_evicted() -> None:
    """Unbounded growth would turn the throttle into a memory exhaustion vector."""
    now = [1000.0]
    limiter = RateLimiter(max_attempts=5, window_seconds=60, clock=lambda: now[0])

    for index in range(500):
        limiter.record(f"key-{index}")
    assert limiter.tracked_keys() == 500

    now[0] += 61
    limiter.record("fresh")

    assert limiter.tracked_keys() == 1


def test_key_count_is_capped_even_within_the_window() -> None:
    """A flood of distinct keys must not grow the table without bound."""
    limiter = RateLimiter(max_attempts=5, window_seconds=3600, max_keys=100)

    for index in range(1000):
        limiter.record(f"key-{index}")

    assert limiter.tracked_keys() <= 100
