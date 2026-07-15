"""Registry-driven RSS and Atom provider for exactly one source."""

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin

import feedparser

from procuresignal.retrieval.base import FetchResult, NewsProvider, RawArticle
from procuresignal.retrieval.catalog import REGISTRY_VERSION
from procuresignal.retrieval.deduplication import canonicalize_url
from procuresignal.retrieval.registry import ProcurementDomain, SourceDefinition

_MAX_TITLE = 500
_MAX_TEXT = 2_000


class _Fetcher(Protocol):
    async def fetch(self, source: SourceDefinition) -> FetchResult:
        ...


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.parts.append(data)


def _plain_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    parser = _TextExtractor()
    parser.feed(html.unescape(str(value)))
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text[:limit] or None


def _timestamp(entry: dict, now: datetime) -> tuple[datetime, str | None]:
    raw = entry.get("published") or entry.get("updated")
    parsed: datetime | None = None
    if raw:
        try:
            parsed = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                pass
    if parsed is None:
        parsed = now
    elif parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return (min(parsed, now), str(raw) if raw else None)


def _primary_domain(source: SourceDefinition) -> str:
    return next(domain.value for domain in ProcurementDomain if domain in source.domains)


class RSSProvider(NewsProvider):
    """Fetch and parse the single registry source supplied at construction."""

    def __init__(self, source: SourceDefinition, fetcher: _Fetcher) -> None:
        self.name = "rss"
        self.source = source
        self.fetcher = fetcher

    async def close(self) -> None:
        """The injected fetcher lifecycle remains owned by its caller."""

    async def health_check(self) -> bool:
        return (await self.fetcher.fetch(self.source)).ok

    async def fetch_articles(self, query_groups: list[str]) -> list[RawArticle]:
        del query_groups  # compatibility input; registry domains are authoritative
        result = await self.fetcher.fetch(self.source)
        if not result.ok or result.content is None:
            return []
        parsed = feedparser.parse(result.content)
        now = datetime.utcnow()
        base_url = result.final_url or self.source.endpoint_url
        feed_language = parsed.feed.get("language")
        articles: list[RawArticle] = []
        for entry in parsed.entries[: self.source.item_limit]:
            link = urljoin(base_url, str(entry.get("link") or ""))
            if not link:
                continue
            description = _plain_text(
                entry.get("summary")
                or entry.get("description")
                or entry.get("content", [{}])[0].get("value"),
                _MAX_TEXT,
            )
            published_at, published_raw = _timestamp(entry, now)
            title = _plain_text(entry.get("title"), _MAX_TITLE) or ""
            language = str(
                entry.get("language") or feed_language or self.source.languages[0]
            ).lower()
            articles.append(
                RawArticle(
                    provider="rss",
                    provider_article_id=str(entry.get("id") or entry.get("guid") or link),
                    query_group=_primary_domain(self.source),
                    title=title,
                    description=description,
                    content_snippet=description,
                    article_url=link,
                    canonical_url=canonicalize_url(link),
                    source_name=self.source.display_name,
                    source_url=self.source.homepage_url,
                    published_at=published_at,
                    language=language,
                    raw_payload_json={"id": entry.get("id"), "link": link, "title": title},
                    source_id=self.source.source_id,
                    source_class=self.source.source_class.value,
                    source_domains=tuple(sorted(domain.value for domain in self.source.domains)),
                    source_countries=self.source.countries,
                    registry_version=REGISTRY_VERSION,
                    retrieved_at=now,
                    source_published_at_raw=published_raw,
                )
            )
        return articles
