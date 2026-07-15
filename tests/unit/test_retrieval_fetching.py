import ipaddress
from datetime import datetime, timezone

import httpcore
import httpx
import pytest

from shared.procuresignal.retrieval.catalog import SOURCE_REGISTRY
from shared.procuresignal.retrieval.fetching import (
    FetchFailureCode,
    PinnedNetworkBackend,
    SafeFetcher,
    SecureTransport,
    parse_retry_after,
)
from shared.procuresignal.retrieval.security import URLSafetyPolicy

SOURCE = SOURCE_REGISTRY.sources[0]


class MemoryCircuit:
    async def allow_circuit_request(self, source_id, owner, now):
        return True

    async def record_circuit_failure(self, source_id, now):
        return None

    async def record_circuit_success(self, source_id, owner):
        return True


async def public_resolver(host: str, port: int):
    return (ipaddress.ip_address("93.184.216.34"),)


class ApprovedMockTransport(SecureTransport):
    def __init__(self, handler):
        self.mock = httpx.MockTransport(handler)
        self.approved = []
        self.closed = False

    def approve(self, validated):
        self.approved.append(validated)

    async def handle_async_request(self, request):
        return await self.mock.handle_async_request(request)

    async def aclose(self):
        self.closed = True
        await self.mock.aclose()


def fetcher(handler, **kwargs):
    return SafeFetcher(
        transport=ApprovedMockTransport(handler),
        policy=URLSafetyPolicy(resolver=public_resolver),
        circuit_store=MemoryCircuit(),
        owner="test-worker",
        **kwargs,
    )


def test_fetcher_rejects_unpinned_transport() -> None:
    with pytest.raises(TypeError):
        SafeFetcher(
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
            policy=URLSafetyPolicy(resolver=public_resolver),
            circuit_store=MemoryCircuit(),
            owner="test",
        )


async def test_pinned_backend_connects_to_approved_ip_not_rebound_hostname() -> None:
    class RebindingBackend(httpcore.AsyncNetworkBackend):
        def __init__(self):
            self.connected_host = None

        async def connect_tcp(
            self, host, port, timeout=None, local_address=None, socket_options=None
        ):
            self.connected_host = host
            return httpcore.AsyncMockStream([])

        async def connect_unix_socket(self, path, timeout=None, socket_options=None):
            raise AssertionError("not used")

        async def sleep(self, seconds):
            return None

    ordinary_dns_would_rebind = RebindingBackend()
    backend = PinnedNetworkBackend(ordinary_dns_would_rebind)
    validated = await URLSafetyPolicy(resolver=public_resolver).validate(
        SOURCE.endpoint_url, SOURCE.allowed_hosts
    )
    backend.approve(validated)
    await backend.connect_tcp(validated.host, 443)
    assert ordinary_dns_would_rebind.connected_host == "93.184.216.34"


def test_secure_client_enforces_bounded_timeouts() -> None:
    f = fetcher(lambda request: httpx.Response(500))
    assert f._client.timeout.connect == 5
    assert f._client.timeout.read == 20
    assert f._client.timeout.write == 20
    assert f._client.timeout.pool == 5


async def test_fetcher_approves_resolved_ip_for_actual_transport() -> None:
    transport = ApprovedMockTransport(
        lambda request: httpx.Response(
            200, content=b"ok", headers={"content-type": SOURCE.expected_content_types[0]}
        )
    )
    async with SafeFetcher(
        transport=transport,
        policy=URLSafetyPolicy(resolver=public_resolver),
        circuit_store=MemoryCircuit(),
        owner="test-worker",
    ) as f:
        assert (await f.fetch(SOURCE)).ok
    assert str(transport.approved[0].addresses[0]) == "93.184.216.34"
    assert transport.closed


def test_retry_after_is_timezone_safe_finite_and_capped() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    assert parse_retry_after("999999", now=now) == 900
    assert parse_retry_after("Sun, 13 Jul 2026 12:10:00 GMT", now=now) == 600
    assert parse_retry_after("nan", now=now) is None
    assert parse_retry_after("garbage", now=now) is None


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


async def test_503_is_classified_transient_after_attempts_exhausted() -> None:
    fail = fetcher(lambda request: httpx.Response(503), max_attempts=1)
    for _ in range(5):
        result = await fail.fetch(SOURCE)
    assert result.failure_code is FetchFailureCode.TRANSIENT_HTTP_STATUS


async def test_deterministic_404_is_not_retried() -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    result = await fetcher(handler).fetch(SOURCE)
    assert result.failure_code is FetchFailureCode.HTTP_STATUS
    assert calls == 1


async def test_redirect_limit_is_exactly_three() -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": SOURCE.endpoint_url})

    assert (
        await fetcher(handler).fetch(SOURCE)
    ).failure_code is FetchFailureCode.TOO_MANY_REDIRECTS
    assert calls == 4
