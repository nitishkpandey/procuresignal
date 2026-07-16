"""Deterministic, bounded deduplication for one retrieval run."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
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


def _datetime_key(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat()


def _payload_projection(value: object, active: set[int] | None = None) -> object:
    """Convert JSON-like and accidental opaque payload values into stable data."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"$float": repr(value)}
    if isinstance(value, bytes):
        return {"$bytes": value.hex()}
    if isinstance(value, datetime):
        return {"$datetime": _datetime_key(value)}
    identity = id(value)
    if identity in active:
        value_type = type(value)
        return {"$cycle_type": f"{value_type.__module__}.{value_type.__qualname__}"}
    active.add(identity)
    try:
        if isinstance(value, dict):
            pairs = [
                (_payload_projection(key, active), _payload_projection(item, active))
                for key, item in value.items()
            ]
            pairs.sort(key=lambda pair: json.dumps(pair, sort_keys=True, separators=(",", ":")))
            return {"$dict": pairs}
        if isinstance(value, (list, tuple)):
            return {"$sequence": [_payload_projection(item, active) for item in value]}
        if isinstance(value, (set, frozenset)):
            items = [_payload_projection(item, active) for item in value]
            items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
            return {"$set": items}
        value_type = type(value)
        opaque: dict[str, object] = {
            "$opaque_type": f"{value_type.__module__}.{value_type.__qualname__}"
        }
        try:
            state = vars(value)
        except TypeError:
            state = None
        if state:
            opaque["$state"] = _payload_projection(state, active)
        return opaque
    finally:
        active.remove(identity)


def _payload_key(payload: object) -> str:
    return json.dumps(_payload_projection(payload), sort_keys=True, separators=(",", ":"))


def _optional_text(value: str | None) -> str:
    tag = ("none", "") if value is None else ("str", value)
    return json.dumps(tag, separators=(",", ":"))


def _optional_datetime(value: datetime | None) -> str:
    tag = ("none", "") if value is None else ("datetime", _datetime_key(value))
    return json.dumps(tag, separators=(",", ":"))


def _optional_payload(value: dict | None) -> str:
    if value is None:
        return json.dumps(("none", ""), separators=(",", ":"))
    return json.dumps(("payload", _payload_key(value)), separators=(",", ":"))


def _article_projection(article: RawArticle) -> tuple[str, ...]:
    """Return a comparable projection covering every RawArticle field."""
    return (
        article.provider,
        _optional_text(article.provider_article_id),
        article.query_group,
        article.title,
        _optional_text(article.description),
        _optional_text(article.content_snippet),
        article.article_url,
        canonicalize_url(article.canonical_url or article.article_url),
        _optional_text(article.canonical_url),
        article.source_name,
        _optional_text(article.source_url),
        _datetime_key(article.published_at),
        article.language,
        _optional_payload(article.raw_payload_json),
        _optional_text(article.source_id),
        _optional_text(article.source_class),
        "\0".join(article.source_domains),
        "\0".join(article.source_countries),
        _optional_text(article.registry_version),
        _optional_datetime(article.retrieved_at),
        _optional_text(article.source_published_at_raw),
    )


def _preference(article: RawArticle) -> tuple[object, ...]:
    """Sort best authority first, then use a total deterministic article projection."""
    return (-_AUTHORITY.get(article.source_class or "", 0), *_article_projection(article))


def _result_order(article: RawArticle) -> tuple[str, ...]:
    """Provide a total stable order after authority winner selection."""
    return (*_article_projection(article), article_fingerprint(article))


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
