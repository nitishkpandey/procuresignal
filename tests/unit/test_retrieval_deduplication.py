from datetime import datetime, timezone

from procuresignal.retrieval.base import RawArticle
from procuresignal.retrieval.deduplication import article_fingerprint, deduplicate_within_run


def article(
    *, source_class: str, source_id: str, url: str, title: str = "Same event"
) -> RawArticle:
    return RawArticle(
        provider="rss",
        provider_article_id=source_id,
        query_group="logistics",
        title=title,
        description="Bounded description",
        content_snippet="Bounded description",
        article_url=url,
        canonical_url=url,
        source_name=source_id,
        source_url=None,
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        source_id=source_id,
        source_class=source_class,
    )


def test_dedup_prefers_official_source_for_same_canonical_url() -> None:
    media_copy = article(
        source_class="established_media",
        source_id="media",
        url="https://EXAMPLE.com:443/news/1?utm_source=x#top",
    )
    official_item = article(
        source_class="official", source_id="official", url="https://example.com/news/1"
    )
    result = deduplicate_within_run([media_copy, official_item])
    assert result.articles == (official_item,)
    assert result.duplicates == 1


def test_authority_choice_and_tie_break_are_independent_of_input_order() -> None:
    later_id = article(
        source_class="official", source_id="z_official", url="https://example.com/news/1"
    )
    earlier_id = article(
        source_class="official", source_id="a_official", url="https://example.com/news/1"
    )
    assert deduplicate_within_run([later_id, earlier_id]).articles == (earlier_id,)
    assert deduplicate_within_run([earlier_id, later_id]).articles == (earlier_id,)


def test_content_fingerprint_collapses_tracking_url_variants() -> None:
    with_utm = article(
        source_class="industry",
        source_id="one",
        url="https://Example.com:443/a/b?item=7&utm_campaign=x#part",
    )
    without_utm = article(
        source_class="industry", source_id="two", url="https://example.com/a/b?item=7"
    )
    assert article_fingerprint(with_utm) == article_fingerprint(without_utm)


def test_canonicalization_does_not_overcollapse_distinct_content() -> None:
    first = article(source_class="industry", source_id="one", url="https://example.com/a/b?item=7")
    different_path = article(
        source_class="industry", source_id="two", url="https://example.com/b/a?item=7"
    )
    different_query = article(
        source_class="industry", source_id="three", url="https://example.com/a/b?item=8"
    )
    result = deduplicate_within_run([first, different_path, different_query])
    assert len(result.articles) == 3
    assert result.duplicates == 0
