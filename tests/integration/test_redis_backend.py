"""Real broker contract for the distributed authentication rate limiter."""

import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from api.rate_limit import RedisWindow


@pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="REDIS_URL is required")
async def test_attempt_window_is_shared_between_real_redis_clients() -> None:
    """Two API replicas must consume the same attempt budget."""

    url = os.environ["REDIS_URL"]
    first_client = Redis.from_url(url, decode_responses=False)
    second_client = Redis.from_url(url, decode_responses=False)
    key = f"integration:{uuid4()}"
    redis_key = f"ratelimit:{key}"
    first = RedisWindow(first_client, max_attempts=3, window_seconds=60)
    second = RedisWindow(second_client, max_attempts=3, window_seconds=60)

    try:
        await first.record(key)
        await first.record(key)
        assert await second.check(key) is None

        await second.record(key)

        assert await first.check(key) is not None
        assert await second.check(key) is not None
    finally:
        await first_client.delete(redis_key)
        await first_client.aclose()
        await second_client.aclose()
