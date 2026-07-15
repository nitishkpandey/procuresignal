"""Deterministic, bounded deduplication for one retrieval run."""

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import RawArticle

_TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
}
_AUTHORITY = {"official": 3, "established_media": 2, "industry": 1}


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    articles: tuple[RawArticle, ...]
    duplicates: int


def canonicalize_url(url: str) -> str:
    """Normalize transport details and remove known attribution parameters."""
    parsed = urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parsed.port
    if port is not None and not (
        (parsed.scheme.lower() == "https" and port == 443)
        or (parsed.scheme.lower() == "http" and port == 80)
    ):
        hostname = f"{hostname}:{port}"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMETERS
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme.lower(), hostname, parsed.path or "/", query, ""))


def article_fingerprint(article: RawArticle) -> str:
    """Return a stable identity without collapsing distinct paths or content selectors."""
    url = canonicalize_url(article.canonical_url or article.article_url)
    if url:
        material = f"url\0{url}"
    else:
        material = "\0".join(
            (
                "content",
                article.title.casefold().strip(),
                (article.description or "").casefold().strip(),
                article.published_at.isoformat(),
            )
        )
    return sha256(material.encode("utf-8")).hexdigest()


def _preference(article: RawArticle) -> tuple[object, ...]:
    """Sort best authority first, then use stable provenance/content tie-breaks."""
    return (
        -_AUTHORITY.get(article.source_class or "", 0),
        article.source_id or "",
        article.provider_article_id or "",
        canonicalize_url(article.canonical_url or article.article_url),
        article.title,
        article.description or "",
        article.content_snippet or "",
        article.source_name,
        article.language,
        article.published_at.isoformat(),
        article.article_url,
        article.source_url or "",
        article.retrieved_at.isoformat() if article.retrieved_at else "",
        article.source_published_at_raw or "",
        article.source_domains,
        article.source_countries,
        article.registry_version or "",
        json.dumps(article.raw_payload_json, sort_keys=True, default=str),
    )


def _result_order(article: RawArticle) -> tuple[str, ...]:
    """Provide a total stable order after authority winner selection."""
    return (
        article.published_at.isoformat(),
        article.source_id or "",
        article.provider,
        article.provider_article_id or "",
        canonicalize_url(article.canonical_url or article.article_url),
        article_fingerprint(article),
        article.title,
        article.description or "",
        article.content_snippet or "",
        article.source_name,
        article.language,
    )


def deduplicate_within_run(articles: Iterable[RawArticle]) -> DeduplicationResult:
    groups: dict[str, list[RawArticle]] = {}
    total = 0
    for article in articles:
        total += 1
        groups.setdefault(article_fingerprint(article), []).append(article)
    retained = tuple(
        sorted((min(group, key=_preference) for group in groups.values()), key=_result_order)
    )
    return DeduplicationResult(retained, total - len(retained))
