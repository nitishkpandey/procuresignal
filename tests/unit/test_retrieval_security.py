import ipaddress

import pytest

from shared.procuresignal.retrieval.security import UnsafeURL, URLSafetyPolicy


async def resolver(
    host: str, port: int
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    addresses = {
        "official.example": (ipaddress.ip_address("93.184.216.34"),),
        "private.example": (ipaddress.ip_address("10.0.0.1"),),
        "mapped.example": (ipaddress.ip_address("::ffff:127.0.0.1"),),
    }
    return addresses[host]


@pytest.mark.parametrize(
    "url,hosts",
    [
        ("http://official.example/feed", ("official.example",)),
        ("https://user:pass@official.example/feed", ("official.example",)),
        ("https://127.0.0.1/feed", ("127.0.0.1",)),
        ("https://169.254.169.254/latest/meta-data", ("169.254.169.254",)),
        ("https://private.example/feed", ("private.example",)),
        ("https://mapped.example/feed", ("mapped.example",)),
        ("https://evil.example/feed", ("official.example",)),
    ],
)
async def test_url_policy_rejects_unsafe_destinations(url: str, hosts: tuple[str, ...]) -> None:
    with pytest.raises(UnsafeURL):
        await URLSafetyPolicy(resolver=resolver).validate(url, hosts)


async def test_url_policy_returns_resolved_public_destination() -> None:
    result = await URLSafetyPolicy(resolver=resolver).validate(
        "https://official.example/feed", ("official.example",)
    )
    assert result.host == "official.example"
    assert str(result.addresses[0]) == "93.184.216.34"
