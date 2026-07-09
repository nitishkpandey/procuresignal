"""Response helpers for article entity metadata."""

from procuresignal.enrichment.entities import (
    extract_regions_from_text,
    extract_suppliers_from_text,
    merge_entities,
)
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw


def _article_entity_text(processed: NewsArticleProcessed, raw: NewsArticleRaw) -> str:
    return " ".join(
        part
        for part in [
            processed.normalized_title,
            processed.summary,
            raw.title,
            raw.description or "",
            raw.content_snippet or "",
        ]
        if part
    )


def suppliers_for_response(processed: NewsArticleProcessed, raw: NewsArticleRaw) -> list[str]:
    """Return persisted suppliers plus local fallbacks for older rows."""

    return merge_entities(
        processed.detected_suppliers,
        extract_suppliers_from_text(_article_entity_text(processed, raw)),
    )


def regions_for_response(processed: NewsArticleProcessed, raw: NewsArticleRaw) -> list[str]:
    """Return persisted regions plus local fallbacks for older rows."""

    return merge_entities(
        processed.detected_regions,
        extract_regions_from_text(_article_entity_text(processed, raw)),
    )


def categories_for_response(processed: NewsArticleProcessed) -> list[str]:
    """Return detected categories with top-level category as a stable fallback."""

    return merge_entities(processed.detected_categories, [processed.top_level_category])
