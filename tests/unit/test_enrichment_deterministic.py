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
