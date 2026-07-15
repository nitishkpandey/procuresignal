"""Deterministic, bounded deduplication for one retrieval run."""

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
    return urlunsplit((parsed.scheme.lower(), hostname, parsed.path, query, ""))


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
    )


def deduplicate_within_run(articles: Iterable[RawArticle]) -> DeduplicationResult:
    groups: dict[str, list[RawArticle]] = {}
    total = 0
    for article in articles:
        total += 1
        groups.setdefault(article_fingerprint(article), []).append(article)
    retained = tuple(min(group, key=_preference) for group in groups.values())
    return DeduplicationResult(retained, total - len(retained))
