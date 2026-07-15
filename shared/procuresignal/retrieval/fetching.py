"""Bounded, redirect-safe fetching with retry and circuit protection."""

import asyncio
import email.utils
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import urljoin

import httpx

from .base import FetchFailureCode, FetchResult
from .registry import SourceDefinition
from .security import UnsafeURL, URLSafetyPolicy

Sleep = Callable[[float], Awaitable[None]]


class SafeFetcher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        policy: URLSafetyPolicy,
        max_response_bytes: int = 5 * 1024 * 1024,
        max_attempts: int = 3,
        max_redirects: int = 5,
        circuit_threshold: int = 5,
        circuit_cooldown_seconds: float = 60,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.policy = policy
        self.max_response_bytes = max_response_bytes
        self.max_attempts = max_attempts
        self.max_redirects = max_redirects
        self.circuit_threshold = circuit_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.sleep = sleep
        self.clock = clock
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def failure_count(self, source_id: str) -> int:
        return self._failures.get(source_id, 0)

    def _record_failure(self, source_id: str) -> None:
        count = self._failures.get(source_id, 0) + 1
        self._failures[source_id] = count
        if count >= self.circuit_threshold:
            self._opened_at[source_id] = self.clock()

    async def fetch(self, source: SourceDefinition) -> FetchResult:
        opened = self._opened_at.get(source.source_id)
        if opened is not None and self.clock() - opened < self.circuit_cooldown_seconds:
            return FetchResult(failure_code=FetchFailureCode.CIRCUIT_OPEN)
        for attempt in range(self.max_attempts):
            result = await self._attempt(source)
            if result.ok:
                self._failures.pop(source.source_id, None)
                self._opened_at.pop(source.source_id, None)
                return result
            retryable = result.failure_code in {
                FetchFailureCode.NETWORK_ERROR,
                FetchFailureCode.HTTP_STATUS,
            }
            if not retryable or attempt + 1 >= self.max_attempts:
                self._record_failure(source.source_id)
                return result
            await self.sleep(result.retry_after_seconds or min(2**attempt, 30))
        raise AssertionError("unreachable")

    async def _attempt(self, source: SourceDefinition) -> FetchResult:
        url = source.endpoint_url
        for redirect_count in range(self.max_redirects + 1):
            try:
                await self.policy.validate(url, source.allowed_hosts)
                async with self.client.stream("GET", url, follow_redirects=False) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return FetchResult(failure_code=FetchFailureCode.HTTP_STATUS)
                        url = urljoin(url, location)
                        continue
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        return FetchResult(
                            status_code=response.status_code,
                            failure_code=FetchFailureCode.HTTP_STATUS,
                            retry_after_seconds=_retry_after(response.headers.get("Retry-After")),
                        )
                    if response.status_code >= 400:
                        return FetchResult(
                            status_code=response.status_code,
                            failure_code=FetchFailureCode.HTTP_STATUS,
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    expected = {item.lower() for item in source.expected_content_types}
                    if content_type not in expected:
                        return FetchResult(
                            status_code=response.status_code,
                            failure_code=FetchFailureCode.UNEXPECTED_CONTENT_TYPE,
                        )
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > self.max_response_bytes:
                            return FetchResult(failure_code=FetchFailureCode.OVERSIZED_RESPONSE)
                    return FetchResult(bytes(content), content_type, url, response.status_code)
            except UnsafeURL:
                return FetchResult(failure_code=FetchFailureCode.UNSAFE_URL)
            except (httpx.HTTPError, TimeoutError):
                return FetchResult(failure_code=FetchFailureCode.NETWORK_ERROR)
        return FetchResult(failure_code=FetchFailureCode.TOO_MANY_REDIRECTS)


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None


__all__ = ["FetchFailureCode", "FetchResult", "SafeFetcher"]
