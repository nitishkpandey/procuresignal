import inspect
import ipaddress
import json
import stat
from pathlib import Path

import httpx
import pytest
from procuresignal.retrieval.catalog import SOURCE_REGISTRY
from procuresignal.retrieval.fetching import SafeFetcher
from procuresignal.retrieval.large_object import (
    LargeObjectFetcher,
    LargeObjectFetchError,
    MissingSanctionsToken,
)
from procuresignal.retrieval.providers.sanctions import EUSanctionsProvider, UnsafeSanctionsXML
from procuresignal.retrieval.security import URLSafetyPolicy

FIXTURE = Path("tests/fixtures/retrieval/eu_financial_sanctions.xml")
EXPECTED = Path("tests/fixtures/retrieval/eu_financial_sanctions_expected.json")
SOURCE = next(s for s in SOURCE_REGISTRY.sources if s.source_id == "eu_financial_sanctions")


class MemoryCircuit:
    async def allow_circuit_request(self, source_id, owner, now):
        return True

    async def record_circuit_failure(self, source_id, now):
        return None

    async def record_circuit_success(self, source_id, owner):
        return True


async def resolver(host, port):
    return (ipaddress.ip_address("93.184.216.34"),)


class ApprovedTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.mock = httpx.MockTransport(handler)

    def approve(self, validated):
        pass

    async def handle_async_request(self, request):
        return await self.mock.handle_async_request(request)

    async def aclose(self):
        await self.mock.aclose()


def safe_fetcher(handler):
    fetcher = SafeFetcher(
        policy=URLSafetyPolicy(resolver=resolver), circuit_store=MemoryCircuit(), owner="test"
    )
    fetcher._client._transport = ApprovedTransport(handler)
    return fetcher


def test_large_fetcher_has_no_policy_or_transport_override() -> None:
    assert set(inspect.signature(LargeObjectFetcher).parameters) <= {
        "source",
        "fetcher",
        "secret_resolver",
    }


async def test_missing_token_is_stable_configuration_failure(monkeypatch) -> None:
    monkeypatch.delenv("EU_FISMA_SANCTIONS_TOKEN", raising=False)
    fetcher = LargeObjectFetcher(SOURCE, safe_fetcher(lambda request: pytest.fail("request made")))
    with pytest.raises(MissingSanctionsToken, match="EU_FISMA_SANCTIONS_TOKEN is not configured"):
        await fetcher.fetch()


async def test_streams_to_0600_file_redacts_token_and_cleans_up(monkeypatch) -> None:
    token = "top-secret-token"
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", token)
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=b"<root/>")

    fetcher = LargeObjectFetcher(SOURCE, safe_fetcher(handler))
    artifact = await fetcher.fetch()
    async with artifact:
        path = artifact.path
        assert path.read_bytes() == b"<root/>"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert token not in repr(artifact)
        assert token not in str(artifact.final_url)
    assert not path.exists()
    assert token in requests[0]


async def test_oversize_and_cancellation_delete_temporary_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "secret")
    import procuresignal.retrieval.large_object as module

    monkeypatch.setattr(module, "_MAX_DECODED_BYTES", 8)
    created = []
    original = module.tempfile.mkstemp

    def tracked(*args, **kwargs):
        fd, name = original(dir=tmp_path)
        created.append(Path(name))
        return fd, name

    monkeypatch.setattr(module.tempfile, "mkstemp", tracked)

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "application/xml"}, content=b"123456789"
        )

    with pytest.raises(LargeObjectFetchError, match="oversized_response"):
        await LargeObjectFetcher(SOURCE, safe_fetcher(handler)).fetch()
    assert created and all(not p.exists() for p in created)


async def test_network_exception_never_exposes_token(monkeypatch) -> None:
    token = "unobservable-secret"
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", token)

    def handler(request):
        raise httpx.ReadError(f"failed request {request.url}", request=request)

    with pytest.raises(LargeObjectFetchError) as captured:
        await LargeObjectFetcher(SOURCE, safe_fetcher(handler)).fetch()
    assert token not in str(captured.value)
    assert token not in repr(captured.value)
    assert captured.value.__cause__ is None


async def test_fixture_matches_independent_expected_records(monkeypatch) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "fixture-token")
    data = FIXTURE.read_bytes()

    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=data)

    provider = EUSanctionsProvider(SOURCE, safe_fetcher(handler))
    articles = await provider.fetch_articles([])
    actual = [
        {"id": a.provider_article_id, "title": a.title, "description": a.description}
        for a in articles
    ]
    assert actual == json.loads(EXPECTED.read_text())
    assert all(a.query_group == "sanctions" and a.source_class == "official" for a in articles)
    assert all(
        a.source_url == SOURCE.homepage_url and a.article_url == SOURCE.endpoint_url
        for a in articles
    )


@pytest.mark.parametrize(
    "declaration", [b"<!DOCTYPE root>", b"<!ENTITY x SYSTEM 'https://evil.example/x'>"]
)
async def test_rejects_dtd_and_entities_before_parsing(monkeypatch, declaration) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "secret")
    body = declaration + b"<root/>"

    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=body)

    with pytest.raises(UnsafeSanctionsXML):
        await EUSanctionsProvider(SOURCE, safe_fetcher(handler)).fetch_articles([])


def test_large_fetcher_rejects_non_exact_source() -> None:
    other = SOURCE_REGISTRY.sources[0]
    with pytest.raises(ValueError, match="sealed"):
        LargeObjectFetcher(other, safe_fetcher(lambda request: httpx.Response(500)))
