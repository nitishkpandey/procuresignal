"""Tests for the shared rate-limit backend.

The in-process limiter counts per replica and forgets on restart, so N replicas allow
N times the limit and a rolling deploy resets everyone's budget. That is fine as a
stopgap and wrong as a control.
"""

import pytest

from api.rate_limit import RateLimiter, RedisWindow, resolve_backend


class FakeRedis:
    """Enough of the sorted-set API to exercise the sliding window."""

    def __init__(self) -> None:
        self.store: dict[str, list[float]] = {}
        self.expiries: dict[str, int] = {}
        self.fail = False

    def pipeline(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return FakePipeline(self)

    async def ping(self) -> bool:
        if self.fail:
            raise ConnectionError("redis is down")
        return True


class FakePipeline:
    def __init__(self, backend: FakeRedis) -> None:
        self.backend = backend
        self.ops: list = []

    def zremrangebyscore(self, key, _min, cutoff):  # noqa: ANN001
        self.ops.append(("prune", key, cutoff))
        return self

    def zadd(self, key, mapping):  # noqa: ANN001
        self.ops.append(("add", key, list(mapping.values())[0]))
        return self

    def zcard(self, key):  # noqa: ANN001
        self.ops.append(("count", key))
        return self

    def zrange(self, key, start, end, withscores=False):  # noqa: ANN001
        self.ops.append(("oldest", key))
        return self

    def expire(self, key, seconds):  # noqa: ANN001
        self.ops.append(("expire", key, seconds))
        return self

    async def execute(self) -> list:
        if self.backend.fail:
            raise ConnectionError("redis is down")

        results = []
        for op in self.ops:
            kind, key = op[0], op[1]
            window = self.backend.store.setdefault(key, [])
            if kind == "prune":
                cutoff = op[2]
                self.backend.store[key] = [t for t in window if t > cutoff]
                results.append(0)
            elif kind == "add":
                self.backend.store[key].append(op[2])
                results.append(1)
            elif kind == "count":
                results.append(len(self.backend.store[key]))
            elif kind == "oldest":
                current = self.backend.store[key]
                results.append([(b"x", min(current))] if current else [])
            elif kind == "expire":
                self.backend.expiries[key] = op[2]
                results.append(1)
        return results


@pytest.fixture
def window() -> RedisWindow:
    return RedisWindow(FakeRedis(), max_attempts=3, window_seconds=60)


async def test_attempts_below_the_limit_are_allowed(window: RedisWindow) -> None:
    for _ in range(3):
        assert await window.check("ip:email") is None
        await window.record("ip:email")

    assert await window.check("ip:email") is not None


async def test_keys_are_independent(window: RedisWindow) -> None:
    for _ in range(3):
        await window.record("victim")

    assert await window.check("victim") is not None
    assert await window.check("bystander") is None


async def test_the_window_is_shared_across_replicas() -> None:
    """The whole point: two API processes must count against one budget."""
    shared = FakeRedis()
    replica_a = RedisWindow(shared, max_attempts=3, window_seconds=60)
    replica_b = RedisWindow(shared, max_attempts=3, window_seconds=60)

    await replica_a.record("k")
    await replica_a.record("k")
    await replica_b.record("k")

    assert await replica_b.check("k") is not None
    assert await replica_a.check("k") is not None


async def test_keys_expire_so_redis_does_not_grow_forever(window: RedisWindow) -> None:
    await window.record("k")

    assert window.client.expiries, "no TTL set: the key set would grow without bound"


async def test_retry_after_counts_down(window: RedisWindow) -> None:
    for _ in range(3):
        await window.record("k")

    retry_after = await window.check("k")
    assert retry_after is not None and 0 < retry_after <= 60


async def test_a_redis_outage_does_not_refuse_every_login(window: RedisWindow) -> None:
    """Rate limiting is defence in depth. Failing sign-in entirely because Redis
    blinked turns a hardening control into an outage."""
    window.client.fail = True

    assert await window.check("k") is None
    await window.record("k")  # must not raise


async def test_an_outage_is_visible_rather_than_silent(window: RedisWindow) -> None:
    from procuresignal.observability.metrics import RATE_LIMIT_BACKEND_ERRORS

    window.client.fail = True
    before = RATE_LIMIT_BACKEND_ERRORS._value.get()
    await window.check("k")

    assert RATE_LIMIT_BACKEND_ERRORS._value.get() > before


async def test_the_in_process_limiter_still_works_without_redis() -> None:
    """Tests and single-process runs must not need a broker."""
    limiter = RateLimiter(max_attempts=2, window_seconds=60)

    limiter.record("k")
    limiter.record("k")

    assert limiter.check("k") is not None


def test_the_backend_is_chosen_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert resolve_backend() is None

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    assert resolve_backend() is not None
