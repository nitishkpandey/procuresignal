"""DNS-pinned, bounded retrieval with deterministic retry classification."""

import asyncio
import contextvars
import email.utils
import math
import random
import ssl
import time
from datetime import datetime, timezone
from typing import AsyncIterable, Awaitable, Callable, Iterable, Protocol
from urllib.parse import urljoin

import httpcore
import httpx
from httpcore._backends.base import SOCKET_OPTION
from httpx._transports.default import AsyncResponseStream, map_httpcore_exceptions

from .base import FetchFailureCode, FetchResult
from .registry import SourceDefinition
from .security import UnsafeURL, URLSafetyPolicy, ValidatedURL

Sleep = Callable[[float], Awaitable[None]]
UtcClock = Callable[[], datetime]
REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)


class CircuitStore(Protocol):
    async def allow_circuit_request(self, source_id: str, owner: str, now: datetime) -> bool:
        ...

    async def record_circuit_failure(self, source_id: str, now: datetime) -> None:
        ...

    async def record_circuit_success(self, source_id: str, owner: str) -> bool:
        ...


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Substitutes a validated IP only at TCP connect; TLS retains the hostname/SNI."""

    def __init__(self, delegate: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._delegate = delegate or httpcore.AnyIOBackend()
        self._approved: contextvars.ContextVar[dict[str, tuple[str, ...]]] = contextvars.ContextVar(
            "approved_dns", default={}
        )

    def approve(self, validated: ValidatedURL) -> None:
        current = dict(self._approved.get())
        current[validated.host] = tuple(str(address) for address in validated.addresses)
        self._approved.set(current)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        approved = self._approved.get().get(host)
        if not approved:
            raise httpcore.ConnectError("connection destination was not DNS-pinned")
        started = time.monotonic()
        for address in approved:
            remaining = (
                None if timeout is None else max(0.0, timeout - (time.monotonic() - started))
            )
            if remaining == 0:
                break
            try:
                return await self._delegate.connect_tcp(
                    address, port, remaining, local_address, socket_options
                )
            except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout):
                continue
        raise httpcore.ConnectError("all approved destination addresses failed")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are disabled for remote retrieval")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self, backend: PinnedNetworkBackend | None = None) -> None:
        self.backend = backend or PinnedNetworkBackend()
        context = ssl.create_default_context()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=context,
            max_keepalive_connections=0,
            network_backend=self.backend,
        )

    def approve(self, validated: ValidatedURL) -> None:
        self.backend.approve(validated)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.AsyncByteStream):
            raise TypeError("request stream must be asynchronous")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        with map_httpcore_exceptions():
            response = await self._pool.handle_async_request(core_request)
        if not isinstance(response.stream, AsyncIterable):
            raise TypeError("response stream must be asynchronous")
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=AsyncResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


class SafeFetcher:
    def __init__(
        self,
        *,
        policy: URLSafetyPolicy,
        circuit_store: CircuitStore,
        owner: str,
        max_response_bytes: int = 5 * 1024 * 1024,
        max_attempts: int = 3,
        max_redirects: int = 3,
        sleep: Sleep = asyncio.sleep,
        utc_now: UtcClock = lambda: datetime.now(timezone.utc),
        jitter: Callable[[float], float] = lambda base: random.uniform(0.0, base * 0.25),
    ) -> None:
        if max_attempts <= 0 or max_response_bytes <= 0:
            raise ValueError("fetch bounds must be positive")
        self.transport = PinnedAsyncHTTPTransport()
        self.policy = policy
        self.circuit_store = circuit_store
        self.owner = owner
        self.max_response_bytes = min(max_response_bytes, 5 * 1024 * 1024)
        self.max_attempts = min(max_attempts, 3)
        self.max_redirects = min(max_redirects, 3)
        self.sleep = sleep
        self.utc_now = utc_now
        self.jitter = jitter
        self._client = httpx.AsyncClient(
            transport=self.transport,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        )
        self._closed = False

    async def __aenter__(self) -> "SafeFetcher":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            await self._client.aclose()
            self._closed = True

    async def fetch(self, source: SourceDefinition) -> FetchResult:
        if self._closed:
            raise RuntimeError("fetcher is closed")
        now = self.utc_now()
        if not await self.circuit_store.allow_circuit_request(source.source_id, self.owner, now):
            return FetchResult(failure_code=FetchFailureCode.CIRCUIT_OPEN)
        for attempt in range(self.max_attempts):
            result = await self._attempt(source)
            retryable = result.failure_code in {
                FetchFailureCode.NETWORK_ERROR,
                FetchFailureCode.RATE_LIMITED,
                FetchFailureCode.TRANSIENT_HTTP_STATUS,
            }
            if result.ok:
                await self.circuit_store.record_circuit_success(source.source_id, self.owner)
                return result
            if not retryable or attempt + 1 >= self.max_attempts:
                await self.circuit_store.record_circuit_failure(source.source_id, self.utc_now())
                return result
            delay = result.retry_after_seconds
            if delay is None:
                base = min(float(2**attempt), 30.0)
                delay = base + min(max(0.0, self.jitter(base)), base * 0.25, 5.0)
            await self.sleep(min(delay, 900.0))
        raise AssertionError("unreachable")

    async def _attempt(self, source: SourceDefinition) -> FetchResult:
        url = source.endpoint_url
        for _ in range(self.max_redirects + 1):
            try:
                validated = await self.policy.validate(url, source.allowed_hosts)
                self.transport.approve(validated)
                async with self._client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return FetchResult(failure_code=FetchFailureCode.HTTP_STATUS)
                        url = urljoin(url, location)
                        continue
                    if response.status_code == 429:
                        return FetchResult(
                            status_code=429,
                            failure_code=FetchFailureCode.RATE_LIMITED,
                            retry_after_seconds=parse_retry_after(
                                response.headers.get("Retry-After"), now=self.utc_now()
                            ),
                        )
                    if 500 <= response.status_code < 600:
                        return FetchResult(
                            status_code=response.status_code,
                            failure_code=FetchFailureCode.TRANSIENT_HTTP_STATUS,
                        )
                    if response.status_code >= 400:
                        return FetchResult(
                            status_code=response.status_code,
                            failure_code=FetchFailureCode.HTTP_STATUS,
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in {item.lower() for item in source.expected_content_types}:
                        return FetchResult(
                            status_code=response.status_code,
                            failure_code=FetchFailureCode.UNEXPECTED_CONTENT_TYPE,
                        )
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > self.max_response_bytes:
                            return FetchResult(
                                failure_code=FetchFailureCode.OVERSIZED_RESPONSE,
                                response_bytes=len(content),
                            )
                    return FetchResult(
                        bytes(content),
                        content_type,
                        url,
                        response.status_code,
                        response_bytes=len(content),
                    )
            except UnsafeURL:
                return FetchResult(failure_code=FetchFailureCode.UNSAFE_URL)
            except (httpx.HTTPError, TimeoutError):
                return FetchResult(failure_code=FetchFailureCode.NETWORK_ERROR)
        return FetchResult(failure_code=FetchFailureCode.TOO_MANY_REDIRECTS)


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        if not math.isfinite(seconds):
            return None
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        reference = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        seconds = (
            parsed.astimezone(timezone.utc) - reference.astimezone(timezone.utc)
        ).total_seconds()
    return min(900.0, max(0.0, seconds))


__all__ = [
    "FetchFailureCode",
    "FetchResult",
    "PinnedAsyncHTTPTransport",
    "PinnedNetworkBackend",
    "SafeFetcher",
    "parse_retry_after",
]
