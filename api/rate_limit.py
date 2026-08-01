"""In-process throttle for repeated failed credential attempts.

# ponytail: per-process and lost on restart, so N replicas allow N times the limit.
# Redis-backed limiting lands in Phase 3 with the rest of the shared operational
# furniture. This is still worth having now: it turns unlimited online guessing into
# a few attempts per window, which is the difference that matters for a password.
"""

import time
from collections import deque
from collections.abc import Callable

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
