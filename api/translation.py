"""Low-cost translation helpers for user-facing article text."""

from __future__ import annotations

import json
import logging
import os
from hashlib import sha256
from typing import TypeVar

from procuresignal.enrichment.openai_client import OpenAILLMClient

from api.schemas.article import ArticleDetail, SearchResult
from api.schemas.feed import ArticleInFeed
from api.schemas.risk_event import RiskEventItem

logger = logging.getLogger(__name__)

SUPPORTED_TARGETS = {
    "de": "German",
    "fr": "French",
    "es": "Spanish",
}

_TRANSLATION_CACHE: dict[str, dict[str, str | None]] = {}
_FEED_FIELDS = ("title", "summary")
_DETAIL_FIELDS = ("title", "summary", "description", "content_snippet")
_RISK_EVENT_FIELDS = ("evidence_snippet", "recommendation")

ArticleModel = TypeVar("ArticleModel", ArticleInFeed, ArticleDetail, SearchResult, RiskEventItem)


async def translate_feed_articles(
    articles: list[ArticleInFeed],
    language: str | None,
) -> list[ArticleInFeed]:
    """Translate the visible feed article title and summary for non-English users."""

    return await _translate_models(articles, language, _FEED_FIELDS, "feed")


async def translate_search_results(
    results: list[SearchResult],
    language: str | None,
) -> list[SearchResult]:
    """Translate search result title and summary for non-English users."""

    return await _translate_models(results, language, _FEED_FIELDS, "search")


async def translate_article_detail(
    article: ArticleDetail,
    language: str | None,
) -> ArticleDetail:
    """Translate article detail text for non-English users."""

    return (await _translate_models([article], language, _DETAIL_FIELDS, "detail"))[0]


async def translate_risk_events(
    events: list[RiskEventItem],
    language: str | None,
) -> list[RiskEventItem]:
    """Translate user-facing risk event text for non-English users."""

    return await _translate_models(events, language, _RISK_EVENT_FIELDS, "risk-event")


async def _translate_models(
    articles: list[ArticleModel],
    language: str | None,
    fields: tuple[str, ...],
    namespace: str,
) -> list[ArticleModel]:
    target = _target_language(language)
    if not target or not articles:
        return articles

    keyed_items: list[dict[str, str | None]] = []
    missing: list[dict[str, str | None]] = []
    for article in articles:
        values = {field: getattr(article, field, None) for field in fields}
        cache_key = _cache_key(namespace, target, article.id, values)
        cached = _TRANSLATION_CACHE.get(cache_key)
        if cached is not None:
            keyed_items.append({"cache_key": cache_key, **cached})
            continue

        item = {"cache_key": cache_key, "id": str(article.id), **values}
        keyed_items.append(item)
        missing.append(item)

    if missing:
        _TRANSLATION_CACHE.update(await _translate_missing(missing, target, fields))

    translated: list[ArticleModel] = []
    for article, item in zip(articles, keyed_items):
        cached = _TRANSLATION_CACHE.get(str(item["cache_key"]))
        if not cached:
            translated.append(article)
            continue

        update = {
            field: cached.get(field)
            for field in fields
            if isinstance(cached.get(field), str) and str(cached.get(field)).strip()
        }
        translated.append(article.model_copy(update=update))

    return translated


async def _translate_missing(
    items: list[dict[str, str | None]],
    target_language: str,
    fields: tuple[str, ...],
) -> dict[str, dict[str, str | None]]:
    try:
        client = OpenAILLMClient(
            max_tokens=int(os.getenv("OPENAI_TRANSLATION_MAX_TOKENS", "2000")),
            timeout=float(os.getenv("OPENAI_TRANSLATION_TIMEOUT", "30")),
        )
    except ValueError:
        return {}

    batch_size = int(os.getenv("OPENAI_TRANSLATION_BATCH_SIZE", "8"))
    translations: dict[str, dict[str, str | None]] = {}
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        try:
            response = await client.call(
                system_prompt=_system_prompt(target_language, fields),
                user_message=json.dumps(batch, ensure_ascii=False),
            )
            for item in _parse_translation_response(response):
                cache_key = item.get("cache_key")
                if not isinstance(cache_key, str):
                    continue
                translations[cache_key] = {
                    field: item.get(field) if isinstance(item.get(field), str) else None
                    for field in fields
                }
        except Exception as exc:
            logger.warning("Article translation failed: %s", exc)
            continue

    return translations


def _system_prompt(target_language: str, fields: tuple[str, ...]) -> str:
    field_list = ", ".join(fields)
    return (
        f"Translate the provided article {field_list} fields into {target_language}. "
        "Preserve company names, product names, tickers, numbers, currencies, dates, and URLs. "
        "Do not add facts, remove facts, summarize, or explain. "
        "Return only a JSON array. Each item must contain cache_key and the same translated fields."
    )


def _parse_translation_response(response: str) -> list[dict]:
    start = response.find("[")
    end = response.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        parsed = json.loads(response[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _target_language(language: str | None) -> str | None:
    return SUPPORTED_TARGETS.get((language or "en").strip().lower())


def _cache_key(namespace: str, target_language: str, article_id: int, values: dict) -> str:
    digest = sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"{namespace}:{target_language}:{article_id}:{digest[:16]}"
