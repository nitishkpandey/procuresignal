import ipaddress

import httpx

from shared.procuresignal.retrieval.catalog import SOURCE_REGISTRY
from shared.procuresignal.retrieval.fetching import FetchFailureCode, SafeFetcher
from shared.procuresignal.retrieval.security import URLSafetyPolicy

SOURCE = SOURCE_REGISTRY.sources[0]


async def public_resolver(host: str, port: int):
    return (ipaddress.ip_address("93.184.216.34"),)


def fetcher(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SafeFetcher(client=client, policy=URLSafetyPolicy(resolver=public_resolver), **kwargs)


async def test_fetcher_counts_decoded_stream_bytes_and_stops_at_limit() -> None:
    f = fetcher(
        lambda request: httpx.Response(
            200, content=b"x" * 11, headers={"content-type": SOURCE.expected_content_types[0]}
        ),
        max_response_bytes=10,
    )
    result = await f.fetch(SOURCE)
    assert result.failure_code is FetchFailureCode.OVERSIZED_RESPONSE
    assert result.content is None


async def test_fetcher_validates_redirect_host() -> None:
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example/feed"})

    result = await fetcher(handler).fetch(SOURCE)
    assert result.failure_code is FetchFailureCode.UNSAFE_URL


async def test_retry_after_is_honoured_and_503_is_retried() -> None:
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        if calls == 2:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok", headers={"content-type": "application/rss+xml"})

    async def sleep(delay):
        sleeps.append(delay)

    result = await fetcher(handler, sleep=sleep, max_attempts=3).fetch(SOURCE)
    assert result.content == b"ok"
    assert calls == 3
    assert sleeps[0] == 7


async def test_wrong_content_type_is_not_retried() -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"no", headers={"content-type": "text/plain"})

    result = await fetcher(handler).fetch(SOURCE)
    assert result.failure_code is FetchFailureCode.UNEXPECTED_CONTENT_TYPE
    assert calls == 1


async def test_circuit_opens_on_fifth_failure_and_success_resets() -> None:
    now = [100.0]
    fail = fetcher(lambda request: httpx.Response(503), max_attempts=1, clock=lambda: now[0])
    for _ in range(5):
        result = await fail.fetch(SOURCE)
    assert result.failure_code is FetchFailureCode.HTTP_STATUS
    assert (await fail.fetch(SOURCE)).failure_code is FetchFailureCode.CIRCUIT_OPEN
    now[0] += 61
    fail.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"ok", headers={"content-type": SOURCE.expected_content_types[0]}
            )
        )
    )
    assert (await fail.fetch(SOURCE)).ok
    assert fail.failure_count(SOURCE.source_id) == 0
