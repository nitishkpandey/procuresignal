"""Incremental, factual adapter for the official EU sanctions XML export."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from xml.etree.ElementTree import iterparse

from procuresignal.retrieval.base import NewsProvider, RawArticle
from procuresignal.retrieval.catalog import REGISTRY_VERSION
from procuresignal.retrieval.fetching import SafeFetcher
from procuresignal.retrieval.large_object import LargeObjectFetcher
from procuresignal.retrieval.registry import AdapterType, SourceClass, SourceDefinition

_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_TEXT_LIMIT = 2_000


class UnsafeSanctionsXML(ValueError):  # noqa: N818 -- domain-specific public interface
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean(value: str | None, limit: int = _TEXT_LIMIT) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def _check_xml(path: Path) -> None:
    with path.open("rb") as stream:
        overlap = b""
        while chunk := stream.read(64 * 1024):
            candidate = overlap + chunk
            if _DECLARATION.search(candidate):
                raise UnsafeSanctionsXML("DTD and entity declarations are forbidden")
            overlap = candidate[-32:]


def _records(path: Path) -> Iterator[tuple[str, str, bool, str, datetime]]:
    _check_xml(path)
    seen_revisions: set[str] = set()
    for _, element in iterparse(path, events=("end",)):
        if _local(element.tag) != "sanctionEntity":
            continue
        reference = _clean(
            element.attrib.get("euReferenceNumber") or element.attrib.get("logicalId"), 100
        )
        revision = _clean(
            element.attrib.get("designationDate")
            or element.attrib.get("lastUpdated")
            or element.attrib.get("logicalId"),
            40,
        )
        aliases: list[str] = []
        primary = ""
        regulations: list[str] = []
        remarks = ""
        entity = False
        for child in element.iter():
            kind = _local(child.tag)
            if kind == "nameAlias":
                name = _clean(child.attrib.get("wholeName") or child.text, 500)
                if name and name not in aliases:
                    aliases.append(name)
                if name and (not primary or child.attrib.get("strong", "").lower() == "true"):
                    primary = name
            elif kind == "regulation":
                regulation = _clean(child.attrib.get("numberTitle") or child.text, 500)
                if regulation and regulation not in regulations:
                    regulations.append(regulation)
            elif kind == "remark":
                remarks = _clean(child.text)
            elif kind == "subjectType":
                code = (
                    child.attrib.get("code", "") + child.attrib.get("classificationCode", "")
                ).lower()
                entity = code.startswith("e") or "enterprise" in code or "entity" in code
        primary = primary or (aliases[0] if aliases else reference)
        identity = f"eu-sanctions:{reference}:{revision}"
        is_update = reference in seen_revisions
        seen_revisions.add(reference)
        facts = ["Entity" if entity else "Person", f"EU reference {reference}"]
        secondary = [name for name in aliases if name != primary]
        if secondary:
            facts.append("aliases: " + ", ".join(secondary))
        if regulations:
            facts.append("regulations: " + ", ".join(regulations))
        if remarks:
            facts.append("remarks: " + remarks)
        date = (
            datetime.fromisoformat(revision).replace(tzinfo=timezone.utc)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", revision)
            else datetime.now(timezone.utc)
        )
        yield identity, primary, is_update, "; ".join(facts)[:_TEXT_LIMIT], date
        element.clear()


class EUSanctionsProvider(NewsProvider):
    def __init__(self, source: SourceDefinition, fetcher: SafeFetcher) -> None:
        if (
            source.adapter is not AdapterType.STRUCTURED_SANCTIONS
            or source.source_class is not SourceClass.OFFICIAL
        ):
            raise ValueError(
                "EU sanctions provider requires the reviewed official structured source"
            )
        self.name = "eu_sanctions"
        self.source = source
        self.fetcher = LargeObjectFetcher(source, fetcher)

    async def close(self) -> None:
        pass

    async def health_check(self) -> bool:
        artifact = await self.fetcher.fetch()
        async with artifact:
            return True

    async def fetch_articles(self, query_groups: list[str]) -> list[RawArticle]:
        del query_groups
        artifact = await self.fetcher.fetch()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with artifact:
            articles: list[RawArticle] = []
            for identity, name, update, description, published in _records(artifact.path):
                if len(articles) >= self.source.item_limit:
                    break
                published_naive = published.astimezone(timezone.utc).replace(tzinfo=None)
                articles.append(
                    RawArticle(
                        provider="eu_sanctions",
                        provider_article_id=identity,
                        query_group="sanctions",
                        title=f"EU sanctions designation{' update' if update else ''}: {name}",
                        description=description,
                        content_snippet=description,
                        article_url=self.source.endpoint_url,
                        canonical_url=self.source.endpoint_url,
                        source_name=self.source.display_name,
                        source_url=self.source.homepage_url,
                        published_at=published_naive,
                        language="en",
                        raw_payload_json={"designation_id": identity},
                        source_id=self.source.source_id,
                        source_class="official",
                        source_domains=tuple(sorted(d.value for d in self.source.domains)),
                        source_countries=self.source.countries,
                        registry_version=REGISTRY_VERSION,
                        retrieved_at=now,
                        source_published_at_raw=published.date().isoformat(),
                    )
                )
            return articles


__all__ = ["EUSanctionsProvider", "UnsafeSanctionsXML"]
