from datetime import UTC, datetime

import pytest
from procuresignal.enrichment.deterministic import DeterministicEnricher
from procuresignal.retrieval import RawArticle


def article(
    *,
    title: str = "Automotive supply update",
    description: str | None = None,
    content_snippet: str | None = None,
    query_group: str = "automotive",
    source_name: str = "Industry Wire",
) -> RawArticle:
    return RawArticle(
        provider="test",
        provider_article_id="1",
        query_group=query_group,
        title=title,
        description=description,
        content_snippet=content_snippet,
        article_url="https://example.com/article",
        canonical_url=None,
        source_name=source_name,
        source_url=None,
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_extracts_signals_entities_category_and_bounded_scores() -> None:
    analysis = DeterministicEnricher().analyze(
        article(
            title="Automotive tariff update",
            description="Bosch faces a tariff on automotive parts shipped from Germany.",
        ),
        summary_max_chars=120,
    )

    assert analysis.output.category == "automotive"
    assert analysis.output.signal_tags == ["tariff"]
    assert analysis.output.detected_suppliers == ["Bosch"]
    assert analysis.output.detected_regions == ["Germany"]
    assert len(analysis.output.summary) <= 120
    assert 0.0 <= analysis.relevance <= 1.0
    assert 0.0 <= analysis.confidence <= 1.0


@pytest.mark.parametrize(
    ("description", "snippet", "expected"),
    [
        ("Description supplies the preferred summary.", "Snippet is secondary.", "Description"),
        (None, "Snippet supplies the fallback summary.", "Snippet"),
        (None, None, "Automotive supply update"),
    ],
)
def test_summary_falls_back_from_description_to_snippet_to_title(
    description: str | None, snippet: str | None, expected: str
) -> None:
    output = DeterministicEnricher().analyze(
        article(description=description, content_snippet=snippet), summary_max_chars=120
    ).output

    assert output.summary.startswith(expected)


def test_summary_truncation_is_stable_and_respects_bound() -> None:
    source = "Bosch announced an automotive supply update for Germany with several additional details."
    enricher = DeterministicEnricher()

    first = enricher.analyze(article(description=source), summary_max_chars=40).output.summary
    second = enricher.analyze(article(description=source), summary_max_chars=40).output.summary

    assert first == second
    assert first == "Bosch announced an automotive supply…"
    assert len(first) <= 40


def test_word_boundary_truncation_preserves_minimum_at_ten_chars() -> None:
    summary = DeterministicEnricher().analyze(
        article(description="This is sufficiently long"),
        summary_max_chars=10,
    ).output.summary

    assert summary == "This is s…"
    assert len(summary) == 10


def test_general_news_has_no_signal_and_low_relevance() -> None:
    analysis = DeterministicEnricher().analyze(
        article(
            title="Local museum extends weekend hours",
            description="The exhibition opens to visitors on Saturday morning.",
            query_group="general",
            source_name="Local News",
        ),
        summary_max_chars=120,
    )

    assert analysis.output.category == "general"
    assert analysis.output.signal_tags == []
    assert analysis.output.priority_signal is None
    assert analysis.relevance < 0.35


def test_multiple_signals_preserve_classifier_order() -> None:
    output = DeterministicEnricher().analyze(
        article(description="Bosch faces a tariff and a labor strike in Germany."),
        summary_max_chars=120,
    ).output

    assert output.signal_tags == ["tariff", "strike"]
    assert output.priority_signal == "tariff"


def test_entities_are_deduplicated_across_article_fields() -> None:
    output = DeterministicEnricher().analyze(
        article(
            title="Bosch strike in Germany",
            description="Bosch workers in Germany began a strike.",
            content_snippet="Bosch operations across Germany were affected.",
        ),
        summary_max_chars=120,
    ).output

    assert output.detected_suppliers == ["Bosch"]
    assert output.detected_regions == ["Germany"]


def test_summary_max_chars_must_support_output_schema() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        DeterministicEnricher().analyze(article(), summary_max_chars=9)


@pytest.mark.parametrize(
    ("title", "description", "snippet", "max_chars"),
    [
        ("", None, None, 10),
        ("   ", "\t", "\n", 40),
        ("Tiny", None, None, 10),
        ("Title fallback", " ", "Short", 40),
    ],
)
def test_summary_is_schema_valid_for_empty_whitespace_and_short_sources(
    title: str,
    description: str | None,
    snippet: str | None,
    max_chars: int,
) -> None:
    summary = DeterministicEnricher().analyze(
        article(title=title, description=description, content_snippet=snippet),
        summary_max_chars=max_chars,
    ).output.summary

    assert 10 <= len(summary) <= max_chars


def test_summary_skips_whitespace_but_preserves_source_preference() -> None:
    summary = DeterministicEnricher().analyze(
        article(
            title="Title fallback text",
            description="   ",
            content_snippet="Snippet preferred over title",
        ),
        summary_max_chars=80,
    ).output.summary

    assert summary.startswith("Snippet preferred over title")


@pytest.mark.parametrize("invalid", [True, False, 10.0, "10"])
def test_summary_max_chars_requires_an_integer_excluding_bool(invalid: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        DeterministicEnricher().analyze(article(), summary_max_chars=invalid)  # type: ignore[arg-type]


def test_clear_content_category_outweighs_conflicting_query_group() -> None:
    output = DeterministicEnricher().analyze(
        article(
            title="Automotive vehicle production expands",
            description="Car manufacturers add a new vehicle assembly line.",
            query_group="regulatory",
        ),
        summary_max_chars=120,
    ).output

    assert output.category == "automotive"


def test_query_group_category_wins_without_stronger_content_evidence() -> None:
    output = DeterministicEnricher().analyze(
        article(
            title="New requirements announced",
            description="Officials published details for affected businesses.",
            query_group="regulatory",
            source_name="Daily Bulletin",
        ),
        summary_max_chars=120,
    ).output

    assert output.category == "regulatory"
