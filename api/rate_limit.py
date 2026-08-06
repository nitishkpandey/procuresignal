"""Throttles for repeated failed credential attempts.

Two backends. The Redis one is a sliding window shared by every replica, which is what
makes the limit mean something once there is more than one API process: an in-process
counter lets N replicas allow N times the limit, and a rolling deploy hands everybody a
fresh budget.

The in-process one remains for single-process runs and for tests, which should not need
a broker to exercise sign-in.

Neither refuses traffic when the backend is unreachable. Rate limiting is defence in
depth; turning a Redis blip into a total sign-in outage trades a small risk for a large
one. Failures increment a counter instead, so degradation is visible rather than
assumed.
"""

import logging
import os
import time
from collections import deque
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Failed sign-ins for one address from one address block.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60

# Registrations from one address block, which create organizations.
REGISTER_MAX_ATTEMPTS = 10
REGISTER_WINDOW_SECONDS = 60 * 60

# Ceiling on distinct tracked keys. Without it, a flood of unique addresses would
# grow the table until the process runs out of memory.
DEFAULT_MAX_KEYS = 10_000


class RateLimiter:
    """A sliding window over recorded attempts, keyed by caller."""

    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: int,
        max_keys: int = DEFAULT_MAX_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}

    def check(self, key: str) -> int | None:
        """Return seconds to wait if `key` is throttled, otherwise `None`."""

        now = self._clock()
        window = self._prune(key, now)
        if window is None or len(window) < self._max_attempts:
            return None
        return max(1, int(window[0] + self._window - now))

    def record(self, key: str) -> None:
        """Record one failed attempt.

        Only failures are recorded, so a user signing in correctly all day is never
        throttled.
        """

        now = self._clock()
        self._evict_expired(now)

        window = self._attempts.setdefault(key, deque())
        window.append(now)
        self._prune(key, now)

        if len(self._attempts) > self._max_keys:
            # Drop the least recently active key. Losing a window early only ever
            # forgives an attacker a few attempts; running out of memory does not.
            oldest = min(self._attempts, key=lambda k: self._attempts[k][-1])
            self._attempts.pop(oldest, None)

    def reset(self) -> None:
        """Forget every recorded attempt. Used between tests."""

        self._attempts.clear()

    def tracked_keys(self) -> int:
        """Number of keys currently held. Exposed for tests and diagnostics."""

        return len(self._attempts)

    def _prune(self, key: str, now: float) -> deque[float] | None:
        window = self._attempts.get(key)
        if window is None:
            return None

        cutoff = now - self._window
        while window and window[0] <= cutoff:
            window.popleft()
        if not window:
            del self._attempts[key]
            return None
        return window

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._window
        for key in [k for k, window in self._attempts.items() if window[-1] <= cutoff]:
            del self._attempts[key]


login_limiter = RateLimiter(max_attempts=LOGIN_MAX_ATTEMPTS, window_seconds=LOGIN_WINDOW_SECONDS)
registration_limiter = RateLimiter(
    max_attempts=REGISTER_MAX_ATTEMPTS, window_seconds=REGISTER_WINDOW_SECONDS
)


def login_key(client_ip: str | None, email: str) -> str:
    return f"login:{client_ip or 'unknown'}:{email.strip().lower()}"


def registration_key(client_ip: str | None) -> str:
    return f"register:{client_ip or 'unknown'}"


class RedisWindow:
    """A sliding window held in Redis, shared by every replica.

    Implemented with a sorted set per key: attempts are members scored by timestamp,
    old ones are pruned on each touch, and the key carries a TTL so an abandoned one
    disappears on its own rather than accumulating.
    """

    def __init__(self, client: Any, *, max_attempts: int, window_seconds: int) -> None:
        self.client = client
        self._max_attempts = max_attempts
        self._window = window_seconds

    def _key(self, key: str) -> str:
        return f"ratelimit:{key}"

    async def check(self, key: str) -> int | None:
        """Seconds to wait if throttled, otherwise None."""

        now = time.time()
        try:
            pipeline = self.client.pipeline()
            pipeline.zremrangebyscore(self._key(key), 0, now - self._window)
            pipeline.zcard(self._key(key))
            pipeline.zrange(self._key(key), 0, 0, withscores=True)
            _, count, oldest = await pipeline.execute()
        except Exception:  # noqa: BLE001 - availability beats strictness here
            _record_backend_error()
            return None

        if count < self._max_attempts:
            return None

        earliest = oldest[0][1] if oldest else now
        return max(1, int(earliest + self._window - now))

    async def record(self, key: str) -> None:
        """Record one failed attempt."""

        now = time.time()
        try:
            pipeline = self.client.pipeline()
            pipeline.zremrangebyscore(self._key(key), 0, now - self._window)
            pipeline.zadd(self._key(key), {f"{now}": now})
            # TTL slightly beyond the window, so a key nobody touches again expires
            # instead of living in Redis forever.
            pipeline.expire(self._key(key), self._window + 60)
            await pipeline.execute()
        except Exception:  # noqa: BLE001 - never let accounting break sign-in
            _record_backend_error()


def _record_backend_error() -> None:
    from api.metrics import record_rate_limit_backend_error

    logger.warning("rate limit backend unavailable; falling open for this request")
    record_rate_limit_backend_error()


def resolve_backend() -> Any | None:
    """An async Redis client when one is configured, otherwise None.

    Returning None is how the in-process limiter stays the default for tests and
    single-process runs.
    """

    url = os.getenv("REDIS_URL")
    if not url:
        return None

    from redis.asyncio import Redis

    return Redis.from_url(url, decode_responses=False)


# Resolved once at import. A shared window when REDIS_URL is set, the in-process one
# otherwise, so tests and single-process runs need no broker.
_client = resolve_backend()

login_window: RedisWindow | None = (
    RedisWindow(_client, max_attempts=LOGIN_MAX_ATTEMPTS, window_seconds=LOGIN_WINDOW_SECONDS)
    if _client is not None
    else None
)
registration_window: RedisWindow | None = (
    RedisWindow(_client, max_attempts=REGISTER_MAX_ATTEMPTS, window_seconds=REGISTER_WINDOW_SECONDS)
    if _client is not None
    else None
)


async def check_login(key: str) -> int | None:
    """Seconds to wait before this key may attempt sign-in again."""

    if login_window is not None:
        return await login_window.check(key)
    return login_limiter.check(key)


async def record_login_failure(key: str) -> None:
    if login_window is not None:
        await login_window.record(key)
    else:
        login_limiter.record(key)


async def check_registration(key: str) -> int | None:
    if registration_window is not None:
        return await registration_window.check(key)
    return registration_limiter.check(key)


async def record_registration_failure(key: str) -> None:
    if registration_window is not None:
        await registration_window.record(key)
    else:
        registration_limiter.record(key)
