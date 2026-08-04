import asyncio
import inspect
import ipaddress
import json
import logging
import stat
from pathlib import Path
from xml.etree.ElementTree import ParseError

import httpx
import pytest
from procuresignal.models import Base, NewsArticleRaw
from procuresignal.retrieval.base import FetchFailureCode
from procuresignal.retrieval.catalog import SOURCE_REGISTRY
from procuresignal.retrieval.deduplication import deduplicate_within_run
from procuresignal.retrieval.fetching import SafeFetcher
from procuresignal.retrieval.large_object import (
    LargeObjectFetcher,
    LargeObjectFetchError,
    MissingSanctionsToken,
)
from procuresignal.retrieval.persistence import ArticlePersistence
from procuresignal.retrieval.providers.sanctions import EUSanctionsProvider, UnsafeSanctionsXML
from procuresignal.retrieval.security import URLSafetyPolicy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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


def safe_fetcher(handler, **kwargs):
    fetcher = SafeFetcher(
        policy=URLSafetyPolicy(resolver=resolver),
        circuit_store=MemoryCircuit(),
        owner="test",
        **kwargs,
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
    with pytest.raises(MissingSanctionsToken, match="configuration_error") as captured:
        await fetcher.fetch()
    assert captured.value.failure_code is FetchFailureCode.CONFIGURATION_ERROR


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


@pytest.mark.parametrize("status_code", [200, 503])
async def test_http_client_success_and_error_logs_never_expose_token(
    monkeypatch, caplog, status_code
) -> None:
    token = "caplog-secret-token"
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", token)
    caplog.set_level(logging.DEBUG)

    def handler(request):
        logging.getLogger("httpcore.connection").debug("request=%s", request.url)
        return httpx.Response(
            status_code,
            headers={"content-type": "application/xml"},
            content=b"<root/>",
        )

    fetcher = LargeObjectFetcher(SOURCE, safe_fetcher(handler, max_attempts=1))
    if status_code == 200:
        artifact = await fetcher.fetch()
        artifact.cleanup()
    else:
        with pytest.raises(LargeObjectFetchError):
            await fetcher.fetch()

    assert token not in caplog.text
    assert all(token not in record.getMessage() for record in caplog.records)


async def test_retry_after_and_jitter_are_preserved(monkeypatch) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "retry-secret")
    sleeps: list[float] = []
    responses = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503),
        httpx.Response(200, headers={"content-type": "application/xml"}, content=b"<root/>"),
    ]

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(_request):
        return responses.pop(0)

    fetcher = safe_fetcher(
        handler,
        sleep=record_sleep,
        jitter=lambda base: base * 0.25,
    )
    artifact = await LargeObjectFetcher(SOURCE, fetcher).fetch()
    artifact.cleanup()

    assert sleeps == [7.0, 2.5]


async def test_redirect_never_forwards_credentials(monkeypatch) -> None:
    token = "redirect-secret"
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", token)
    requests: list[str] = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/stolen"})

    with pytest.raises(LargeObjectFetchError) as captured:
        await LargeObjectFetcher(SOURCE, safe_fetcher(handler, max_attempts=1)).fetch()

    assert captured.value.failure_code is FetchFailureCode.TOO_MANY_REDIRECTS
    assert len(requests) == 1
    assert token in requests[0]
    assert "evil.example" not in requests[0]


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


@pytest.mark.parametrize(
    ("bom", "encoding"),
    [
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
        # expat auto-detects UTF-16 with no BOM, so the guard cannot rely on one.
        (b"", "utf-16-le"),
        (b"", "utf-16-be"),
    ],
)
async def test_rejects_utf16_dtd_entity_expansion(monkeypatch, bom, encoding) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "secret")
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE export [<!ENTITY expanded "EXPANDED">]>'
        '<export><sanctionEntity euReferenceNumber="EU.X" designationDate="2026-01-01">'
        '<nameAlias wholeName="&expanded;" /></sanctionEntity></export>'
    )
    body = bom + xml.encode(encoding)

    def handler(_request):
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=body)

    with pytest.raises(UnsafeSanctionsXML, match="encoding|BOM"):
        await EUSanctionsProvider(SOURCE, safe_fetcher(handler)).fetch_articles([])


async def test_cancellation_after_file_creation_deletes_artifact(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "cancel-secret")
    import procuresignal.retrieval.large_object as module

    created: list[Path] = []
    original = module.tempfile.mkstemp
    streaming = asyncio.Event()

    def tracked(*args, **kwargs):
        fd, name = original(dir=tmp_path)
        created.append(Path(name))
        return fd, name

    class BlockingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"<root>"
            streaming.set()
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(module.tempfile, "mkstemp", tracked)

    def handler(_request):
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            stream=BlockingStream(),
        )

    task = asyncio.create_task(LargeObjectFetcher(SOURCE, safe_fetcher(handler)).fetch())
    await streaming.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert created and all(not path.exists() for path in created)


async def test_parser_error_deletes_artifact(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "parser-secret")
    import procuresignal.retrieval.large_object as module

    created: list[Path] = []
    original = module.tempfile.mkstemp

    def tracked(*args, **kwargs):
        fd, name = original(dir=tmp_path)
        created.append(Path(name))
        return fd, name

    monkeypatch.setattr(module.tempfile, "mkstemp", tracked)

    def handler(_request):
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=b"<export><sanctionEntity>",
        )

    with pytest.raises(ParseError):
        await EUSanctionsProvider(SOURCE, safe_fetcher(handler)).fetch_articles([])

    assert created and all(not path.exists() for path in created)


async def test_designation_revision_output_is_stable_under_record_reordering(monkeypatch) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "order-secret")
    older = (
        '<sanctionEntity euReferenceNumber="EU.001" designationDate="2024-01-02">'
        '<nameAlias wholeName="Stable Name" strong="true" /></sanctionEntity>'
    )
    newer = (
        '<sanctionEntity designationDate="2025-02-04" euReferenceNumber="EU.001">'
        '<nameAlias strong="true" wholeName="Stable Name" /></sanctionEntity>'
    )

    async def parsed(body: bytes) -> dict[str | None, str]:
        def handler(_request):
            return httpx.Response(
                200,
                headers={"content-type": "application/xml"},
                content=body,
            )

        articles = await EUSanctionsProvider(SOURCE, safe_fetcher(handler)).fetch_articles([])
        return {article.provider_article_id: article.title for article in articles}

    forward = await parsed(f"<export>{older}{newer}</export>".encode())
    reverse = await parsed(f"<export>{newer}{older}</export>".encode())

    assert (
        forward
        == reverse
        == {
            "eu-sanctions:EU.001:2024-01-02": "EU sanctions designation: Stable Name",
            "eu-sanctions:EU.001:2025-02-04": "EU sanctions designation update: Stable Name",
        }
    )


async def test_provider_identity_survives_deduplication_and_persistence(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "identity-secret")
    body = b"""<export>
      <sanctionEntity euReferenceNumber="EU.A" designationDate="2026-01-01">
        <nameAlias wholeName="Same Name" strong="true" />
      </sanctionEntity>
      <sanctionEntity euReferenceNumber="EU.B" designationDate="2026-01-01">
        <nameAlias wholeName="Same Name" strong="true" />
      </sanctionEntity>
    </export>"""

    def handler(_request):
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=body)

    articles = await EUSanctionsProvider(SOURCE, safe_fetcher(handler)).fetch_articles([])
    deduped = deduplicate_within_run(reversed(articles))
    assert deduped.duplicates == 0
    assert {article.provider_article_id for article in deduped.articles} == {
        "eu-sanctions:EU.A:2026-01-01",
        "eu-sanctions:EU.B:2026-01-01",
    }

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sanctions.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            first = await ArticlePersistence.save_articles(session, list(deduped.articles))
        async with maker() as session:
            second = await ArticlePersistence.save_articles(
                session, list(reversed(deduped.articles))
            )
            rows = list((await session.scalars(select(NewsArticleRaw))).all())
    finally:
        await engine.dispose()

    assert first == (2, 0, 0)
    assert second == (0, 2, 0)
    assert {row.provider_article_id for row in rows} == {
        "eu-sanctions:EU.A:2026-01-01",
        "eu-sanctions:EU.B:2026-01-01",
    }


async def test_validated_destination_is_pinned_before_token_request(monkeypatch) -> None:
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "pin-secret")
    fetcher = safe_fetcher(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=b"<root/>",
        )
    )
    approvals = []
    monkeypatch.setattr(fetcher.transport, "approve", approvals.append)

    artifact = await LargeObjectFetcher(SOURCE, fetcher).fetch()
    artifact.cleanup()

    assert len(approvals) == 1
    assert approvals[0].host == "webgate.ec.europa.eu"
    assert tuple(str(address) for address in approvals[0].addresses) == ("93.184.216.34",)


def test_large_fetcher_rejects_non_exact_source() -> None:
    other = SOURCE_REGISTRY.sources[0]
    with pytest.raises(ValueError, match="sealed"):
        LargeObjectFetcher(other, safe_fetcher(lambda request: httpx.Response(500)))


async def test_designation_names_are_carried_for_screening(monkeypatch) -> None:
    """Screening must compare every spelling the authority recorded.

    Parsing them back out of the human-readable description would break the moment
    that wording changed.
    """
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "secret")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<export>"
        '<sanctionEntity euReferenceNumber="EU.99" designationDate="2026-01-01">'
        '<nameAlias wholeName="Primary Trading Co" strong="true" />'
        '<nameAlias wholeName="Primary Trading Company" />'
        '<nameAlias wholeName="PTC Holdings" />'
        "</sanctionEntity>"
        "</export>"
    ).encode()

    def handler(_request):
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=xml)

    articles = await EUSanctionsProvider(SOURCE, safe_fetcher(handler)).fetch_articles([])

    names = articles[0].raw_payload_json["designation_names"]
    assert names[0] == "Primary Trading Co"
    assert set(names) == {"Primary Trading Co", "Primary Trading Company", "PTC Holdings"}
