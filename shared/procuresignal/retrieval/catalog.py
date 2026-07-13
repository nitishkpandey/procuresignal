"""Reviewed production catalog for authoritative procurement retrieval."""

from .registry import (
    AdapterType,
    SourceClass,
    SourceDefinition,
    SourceRegistry,
)
from .registry import (
    ProcurementDomain as Domain,
)

REGISTRY_VERSION = "sources-v1"


def _source(
    *,
    source_id: str,
    display_name: str,
    homepage_url: str,
    endpoint_url: str,
    source_class: SourceClass,
    domains: frozenset[Domain],
    countries: tuple[str, ...] = ("eu",),
    languages: tuple[str, ...] = ("en",),
    poll_minutes: int = 60,
    item_limit: int = 50,
    expected_content_types: tuple[str, ...] = (
        "application/rss+xml",
        "application/xml",
        "text/xml",
    ),
    trust_seed: float,
    license_note: str,
    adapter: AdapterType = AdapterType.RSS,
    enabled_by_default: bool = True,
    parser_hint: str | None = None,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=display_name,
        homepage_url=homepage_url,
        endpoint_url=endpoint_url,
        adapter=adapter,
        source_class=source_class,
        domains=domains,
        countries=countries,
        languages=languages,
        poll_minutes=poll_minutes,
        item_limit=item_limit,
        expected_content_types=expected_content_types,
        allowed_hosts=(endpoint_url.split("/", 3)[2],),
        trust_seed=trust_seed,
        license_note=license_note,
        enabled_by_default=enabled_by_default,
        parser_hint=parser_hint,
    )


_SOURCES = (
    _source(
        source_id="eu_commission_press",
        display_name="European Commission Press Corner",
        homepage_url="https://ec.europa.eu/commission/presscorner/home/en",
        endpoint_url="https://ec.europa.eu/commission/presscorner/api/rss?language=en",
        source_class=SourceClass.OFFICIAL,
        domains=frozenset(
            {
                Domain.SANCTIONS,
                Domain.REGULATION,
                Domain.LOGISTICS,
                Domain.COMMODITIES,
                Domain.SUPPLIER_RISK,
                Domain.EUROPE_BUSINESS,
            }
        ),
        trust_seed=0.95,
        license_note="Official public RSS; retain Commission attribution and source links.",
    ),
    _source(
        source_id="eu_council_press",
        display_name="Council of the EU Press Releases",
        homepage_url="https://www.consilium.europa.eu/en/press/press-releases/",
        endpoint_url="https://www.consilium.europa.eu/en/press/press-releases/?rss=true",
        source_class=SourceClass.OFFICIAL,
        domains=frozenset({Domain.SANCTIONS, Domain.REGULATION, Domain.EUROPE_BUSINESS}),
        trust_seed=0.95,
        license_note="Candidate official feed returned HTTP 403 during review; disabled pending access confirmation.",
        enabled_by_default=False,
    ),
    _source(
        source_id="ecb_press",
        display_name="European Central Bank Press",
        homepage_url="https://www.ecb.europa.eu/press/html/index.en.html",
        endpoint_url="https://www.ecb.europa.eu/rss/press.html",
        source_class=SourceClass.OFFICIAL,
        domains=frozenset({Domain.FX, Domain.REGULATION, Domain.EUROPE_BUSINESS}),
        trust_seed=0.95,
        license_note="Official ECB RSS subscription feed; retain attribution and source links.",
    ),
    _source(
        source_id="eu_financial_sanctions",
        display_name="EU Consolidated Financial Sanctions List",
        homepage_url="https://webgate.ec.europa.eu/fsd/fsf/",
        endpoint_url="https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content",
        source_class=SourceClass.OFFICIAL,
        domains=frozenset({Domain.SANCTIONS, Domain.SUPPLIER_RISK}),
        poll_minutes=1440,
        item_limit=100,
        expected_content_types=("application/xml", "text/xml"),
        trust_seed=1.0,
        license_note="Public EU dataset candidate returned HTTP 403 without credentials; disabled pending a supported access path.",
        adapter=AdapterType.STRUCTURED_SANCTIONS,
        enabled_by_default=False,
        parser_hint="eu_fsf_1_1",
    ),
    _source(
        source_id="eurostat_updates",
        display_name="Eurostat Data Updates",
        homepage_url="https://ec.europa.eu/eurostat/",
        endpoint_url="https://ec.europa.eu/eurostat/api/dissemination/catalogue/rss/en/statistics-update.rss",
        source_class=SourceClass.OFFICIAL,
        domains=frozenset(
            {
                Domain.LOGISTICS,
                Domain.COMMODITIES,
                Domain.SUPPLIER_RISK,
                Domain.EUROPE_BUSINESS,
            }
        ),
        poll_minutes=720,
        trust_seed=0.9,
        license_note="Official Eurostat Catalogue API RSS; reuse under the Eurostat reuse policy with attribution.",
    ),
    _source(
        source_id="freightwaves",
        display_name="FreightWaves",
        homepage_url="https://www.freightwaves.com/",
        endpoint_url="https://www.freightwaves.com/feed",
        source_class=SourceClass.INDUSTRY,
        domains=frozenset({Domain.LOGISTICS, Domain.SUPPLIER_RISK}),
        countries=("us",),
        trust_seed=0.72,
        license_note="Disabled: publisher terms limit website content to personal use without permission.",
        enabled_by_default=False,
    ),
    _source(
        source_id="mining_com",
        display_name="MINING.COM",
        homepage_url="https://www.mining.com/",
        endpoint_url="https://www.mining.com/feed/",
        source_class=SourceClass.INDUSTRY,
        domains=frozenset({Domain.COMMODITIES, Domain.SUPPLIER_RISK}),
        countries=("ca",),
        trust_seed=0.72,
        license_note="Publisher permits RSS syndication with links back for full viewing.",
    ),
    _source(
        source_id="oilprice",
        display_name="Oilprice.com",
        homepage_url="https://oilprice.com/",
        endpoint_url="https://oilprice.com/rss/main",
        source_class=SourceClass.INDUSTRY,
        domains=frozenset({Domain.COMMODITIES, Domain.LOGISTICS, Domain.SUPPLIER_RISK}),
        countries=("gb",),
        trust_seed=0.68,
        license_note="Publisher-operated public headline RSS; retain attribution and original links.",
    ),
    _source(
        source_id="supply_chain_dive",
        display_name="Supply Chain Dive",
        homepage_url="https://www.supplychaindive.com/",
        endpoint_url="https://www.supplychaindive.com/feeds/news/",
        source_class=SourceClass.INDUSTRY,
        domains=frozenset({Domain.LOGISTICS, Domain.SUPPLIER_RISK, Domain.EUROPE_BUSINESS}),
        countries=("us",),
        trust_seed=0.72,
        license_note="Publisher-operated public RSS; retain attribution and original article links.",
    ),
    _source(
        source_id="dw_business",
        display_name="Deutsche Welle Business",
        homepage_url="https://www.dw.com/en/business/s-1431",
        endpoint_url="https://rss.dw.com/rdf/rss-en-bus",
        source_class=SourceClass.ESTABLISHED_MEDIA,
        domains=frozenset(
            {
                Domain.REGULATION,
                Domain.COMMODITIES,
                Domain.SUPPLIER_RISK,
                Domain.EUROPE_BUSINESS,
            }
        ),
        countries=("de",),
        trust_seed=0.82,
        license_note="DW public RSS for reader subscription; retain attribution and original links.",
    ),
)

SOURCE_REGISTRY = SourceRegistry(_SOURCES)
