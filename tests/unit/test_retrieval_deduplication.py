from dataclasses import replace
from datetime import datetime, timedelta, timezone

from procuresignal.retrieval.base import RawArticle
from procuresignal.retrieval.deduplication import (
    _payload_key,
    article_fingerprint,
    canonicalize_url,
    deduplicate_within_run,
)


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


def test_same_identity_tie_uses_total_deterministic_article_fields() -> None:
    later = article(source_class="official", source_id="official", url="https://example.com/news/1")
    earlier = replace(later, published_at=later.published_at - timedelta(minutes=1))
    assert deduplicate_within_run([later, earlier]).articles == (earlier,)
    assert deduplicate_within_run([earlier, later]).articles == (earlier,)


def test_total_tie_break_covers_provider_query_and_source_class() -> None:
    first = article(source_class="unranked_b", source_id="same", url="https://example.com/news/1")
    second = replace(
        first,
        provider="gdelt",
        query_group="fx",
        source_class="unranked_a",
    )
    forward = deduplicate_within_run([first, second]).articles
    reverse = deduplicate_within_run([second, first]).articles
    assert forward == reverse
    assert forward[0] == second


def test_optional_none_and_empty_string_have_distinct_total_tie_keys() -> None:
    missing = article(source_class="official", source_id="same", url="https://example.com/news/1")
    missing = replace(missing, provider_article_id=None)
    empty = replace(missing, provider_article_id="")
    forward = deduplicate_within_run([missing, empty]).articles
    reverse = deduplicate_within_run([empty, missing]).articles
    assert forward == reverse
    assert forward[0] == missing


def test_payload_dict_sorts_full_projected_pairs_for_colliding_opaque_keys() -> None:
    class OpaqueKey:
        __slots__ = ()

    first_key = OpaqueKey()
    second_key = OpaqueKey()
    forward = {first_key: "b", second_key: "a"}
    reverse = {second_key: "a", first_key: "b"}
    assert _payload_key(forward) == _payload_key(reverse)


def test_unserializable_raw_payload_never_breaks_deduplication() -> None:
    opaque = object()
    item = replace(
        article(source_class="official", source_id="same", url="https://example.com/news/1"),
        raw_payload_json={"set": {"b", "a"}, "opaque": opaque},
    )
    assert deduplicate_within_run([item]).articles == (item,)


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


def test_complete_result_order_is_independent_of_input_order() -> None:
    official = article(source_class="official", source_id="official", url="https://example.com/b")
    media_copy = article(
        source_class="established_media",
        source_id="media",
        url="https://example.com/b?utm_source=x",
    )
    distinct = article(source_class="industry", source_id="industry", url="https://example.com/a")
    forward = deduplicate_within_run([official, media_copy, distinct])
    reverse = deduplicate_within_run([distinct, media_copy, official])
    assert forward.articles == reverse.articles
    assert forward.articles == (distinct, official)
    assert forward.duplicates == reverse.duplicates == 1


def test_canonicalization_brackets_ipv6_and_normalizes_root_and_default_ports() -> None:
    assert canonicalize_url("https://[2001:db8::1]:443") == "https://[2001:db8::1]/"
    assert canonicalize_url("http://[2001:db8::1]:80/") == "http://[2001:db8::1]/"
    assert canonicalize_url("https://example.com") == canonicalize_url("https://example.com/")
    assert canonicalize_url("https://example.com/a") != canonicalize_url("https://example.com/a/")
