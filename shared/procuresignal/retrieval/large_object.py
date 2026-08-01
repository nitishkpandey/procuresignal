"""Sealed streamed retrieval for the reviewed DG FISMA sanctions export."""

import asyncio
import contextvars
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from .base import FetchFailureCode, FetchResult, RetrievalFetchError
from .fetching import SafeFetcher, parse_retry_after
from .registry import AdapterType, SourceDefinition
from .security import UnsafeURL

_SOURCE_ID = "eu_financial_sanctions"
_HOST = "webgate.ec.europa.eu"
_MAX_DECODED_BYTES = 32 * 1024 * 1024
_CONTENT_TYPES = frozenset({"application/xml", "text/xml"})
_SENSITIVE_TRANSPORT_LOGS = contextvars.ContextVar("sensitive_transport_logs", default=False)
_TRANSPORT_LOGGER_NAMES = (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)


class _SuppressSensitiveTransportLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        del record
        return not _SENSITIVE_TRANSPORT_LOGS.get()


_TRANSPORT_LOG_FILTER = _SuppressSensitiveTransportLogs()
for _logger_name in _TRANSPORT_LOGGER_NAMES:
    logging.getLogger(_logger_name).addFilter(_TRANSPORT_LOG_FILTER)


@contextmanager
def _suppress_sensitive_transport_logs() -> Iterator[None]:
    marker = _SENSITIVE_TRANSPORT_LOGS.set(True)
    try:
        yield
    finally:
        _SENSITIVE_TRANSPORT_LOGS.reset(marker)


class LargeObjectFetchError(RetrievalFetchError):
    """Stable, content-free large download failure."""

    def __init__(
        self,
        code: FetchFailureCode,
        *,
        retry_after_seconds: float | None = None,
        response_bytes: int = 0,
    ) -> None:
        self.failure_code = code
        super().__init__(
            FetchResult(
                failure_code=code,
                retry_after_seconds=retry_after_seconds,
                response_bytes=response_bytes,
            )
        )


class MissingSanctionsToken(LargeObjectFetchError):  # noqa: N818
    """Stable, non-retryable deployment configuration failure."""

    def __init__(self) -> None:
        super().__init__(FetchFailureCode.CONFIGURATION_ERROR)


@dataclass(slots=True)
class TemporaryFetchArtifact:
    path: Path
    content_type: str
    final_url: str
    response_bytes: int

    async def __aenter__(self) -> "TemporaryFetchArtifact":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


class LargeObjectFetcher:
    """Non-configurable exception to the ordinary five MiB retrieval ceiling."""

    def __init__(
        self,
        source: SourceDefinition,
        fetcher: SafeFetcher,
        secret_resolver: Callable[[str], str | None] = os.environ.get,
    ) -> None:
        if not (
            source.source_id == _SOURCE_ID
            and source.adapter is AdapterType.STRUCTURED_SANCTIONS
            and source.allowed_hosts == (_HOST,)
            and urlsplit(source.endpoint_url).hostname == _HOST
            and frozenset(t.lower() for t in source.expected_content_types) <= _CONTENT_TYPES
        ):
            raise ValueError("large-object retrieval is sealed to the reviewed sanctions source")
        if not isinstance(fetcher, SafeFetcher):
            raise TypeError("large-object retrieval requires the concrete pinned SafeFetcher")
        self.source = source
        self.fetcher = fetcher
        self._secret_resolver = secret_resolver

    async def fetch(self) -> TemporaryFetchArtifact:
        token = self._secret_resolver("EU_FISMA_SANCTIONS_TOKEN")
        if not token:
            raise MissingSanctionsToken
        now = self.fetcher.utc_now()
        if not await self.fetcher.circuit_store.allow_circuit_request(
            self.source.source_id, self.fetcher.owner, now
        ):
            raise LargeObjectFetchError(FetchFailureCode.CIRCUIT_OPEN)
        last = FetchFailureCode.NETWORK_ERROR
        for attempt in range(self.fetcher.max_attempts):
            try:
                artifact = await self._attempt(token)
            except LargeObjectFetchError as exc:
                last = exc.failure_code
                if (
                    last
                    not in {
                        FetchFailureCode.NETWORK_ERROR,
                        FetchFailureCode.RATE_LIMITED,
                        FetchFailureCode.TRANSIENT_HTTP_STATUS,
                    }
                    or attempt + 1 >= self.fetcher.max_attempts
                ):
                    await self.fetcher.circuit_store.record_circuit_failure(
                        self.source.source_id, self.fetcher.utc_now()
                    )
                    raise
                delay = exc.result.retry_after_seconds
                if delay is None:
                    base = min(float(2**attempt), 30.0)
                    delay = base + min(
                        max(0.0, self.fetcher.jitter(base)),
                        base * 0.25,
                        5.0,
                    )
                await self.fetcher.sleep(min(delay, 900.0))
            else:
                if not self.fetcher.defer_success:
                    await self.fetcher.circuit_store.record_circuit_success(
                        self.source.source_id, self.fetcher.owner
                    )
                return artifact
        raise LargeObjectFetchError(last)

    async def _attempt(self, token: str) -> TemporaryFetchArtifact:
        fd = -1
        path: Path | None = None
        transferred = False
        try:
            validated = await self.fetcher.policy.validate(
                self.source.endpoint_url, self.source.allowed_hosts
            )
            self.fetcher.transport.approve(validated)
            parts = urlsplit(self.source.endpoint_url)
            query = urlencode({"token": token})
            request_url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
            with _suppress_sensitive_transport_logs():
                async with self.fetcher._client.stream("GET", request_url) as response:
                    retry_after = parse_retry_after(
                        response.headers.get("Retry-After"),
                        now=self.fetcher.utc_now(),
                    )
                    if response.is_redirect:
                        raise LargeObjectFetchError(FetchFailureCode.TOO_MANY_REDIRECTS)
                    if response.status_code == 429:
                        raise LargeObjectFetchError(
                            FetchFailureCode.RATE_LIMITED,
                            retry_after_seconds=retry_after,
                        )
                    if 500 <= response.status_code < 600:
                        raise LargeObjectFetchError(
                            FetchFailureCode.TRANSIENT_HTTP_STATUS,
                            retry_after_seconds=retry_after,
                        )
                    if response.status_code >= 400:
                        raise LargeObjectFetchError(FetchFailureCode.HTTP_STATUS)
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in _CONTENT_TYPES:
                        raise LargeObjectFetchError(FetchFailureCode.UNEXPECTED_CONTENT_TYPE)
                    fd, name = tempfile.mkstemp(prefix="procuresignal-sanctions-")
                    path = Path(name)
                    os.fchmod(fd, 0o600)
                    count = 0
                    with os.fdopen(fd, "wb") as output:
                        fd = -1
                        async for chunk in response.aiter_bytes():
                            count += len(chunk)
                            if count > _MAX_DECODED_BYTES:
                                raise LargeObjectFetchError(
                                    FetchFailureCode.OVERSIZED_RESPONSE,
                                    response_bytes=count,
                                )
                            output.write(chunk)
                    artifact = TemporaryFetchArtifact(
                        path, content_type, self.source.endpoint_url, count
                    )
                    transferred = True
                    return artifact
        except UnsafeURL as exc:
            raise LargeObjectFetchError(FetchFailureCode.UNSAFE_URL) from exc
        except asyncio.CancelledError:
            raise
        except LargeObjectFetchError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            # httpx exceptions may include the request URL (and thus the token).
            del exc
            raise LargeObjectFetchError(FetchFailureCode.NETWORK_ERROR) from None
        finally:
            if fd >= 0:
                os.close(fd)
            if path is not None and not transferred:
                path.unlink(missing_ok=True)

    async def aclose(self) -> None:
        await self.fetcher.aclose()


__all__ = [
    "LargeObjectFetcher",
    "LargeObjectFetchError",
    "MissingSanctionsToken",
    "TemporaryFetchArtifact",
]
