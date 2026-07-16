"""SSRF-resistant URL validation for registry-controlled retrieval."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[tuple[IPAddress, ...]]]


class UnsafeURL(ValueError):  # noqa: N818 -- public interface specified by the design
    """Raised before a request can reach an unsafe destination."""


@dataclass(frozen=True, slots=True)
class ValidatedURL:
    url: str
    host: str
    port: int
    addresses: tuple[IPAddress, ...]


async def _resolve(host: str, port: int) -> tuple[IPAddress, ...]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(ipaddress.ip_address(record[4][0]) for record in records))


def _is_public(address: IPAddress) -> bool:
    candidate = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return (candidate or address).is_global


class URLSafetyPolicy:
    def __init__(self, resolver: Resolver = _resolve) -> None:
        self._resolver = resolver

    async def validate(self, url: str, allowed_hosts: tuple[str, ...]) -> ValidatedURL:
        parsed = urlsplit(url)
        host = parsed.hostname
        normalized_allowed = {item.rstrip(".").lower() for item in allowed_hosts}
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or host.rstrip(".").lower() not in normalized_allowed
        ):
            raise UnsafeURL("URL is not an allowed HTTPS destination")
        port = parsed.port or 443
        try:
            literal = ipaddress.ip_address(host)
            addresses: tuple[IPAddress, ...] = (literal,)
        except ValueError:
            try:
                addresses = await self._resolver(host, port)
            except (OSError, KeyError) as exc:
                raise UnsafeURL("destination cannot be safely resolved") from exc
        if not addresses or any(not _is_public(address) for address in addresses):
            raise UnsafeURL("destination resolves to a non-public address")
        return ValidatedURL(url=url, host=host.lower(), port=port, addresses=addresses)
