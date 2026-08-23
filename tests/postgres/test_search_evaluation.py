"""The harness itself, against the real search stack.

Two things are being verified. That the golden set is internally consistent — every label
names an article that exists — because a typo in a label shows up as a retrieval
regression, which is the most confusing failure this gate can produce. And that the
harness scores a known-good and a known-bad retriever the way it should, since a harness
that reports 1.0 for everything is worse than no harness at all.
"""

from pathlib import Path

import pytest
from procuresignal.evaluation.harness import (
    load_corpus,
    load_golden_set,
    resolve_cases,
    run_evaluation,
)
from procuresignal.search.hybrid import search
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "golden_queries.json"


def test_the_golden_set_is_the_shape_the_plan_specified() -> None:
    """Twelve queries, including the two whose right answer is nothing. Without those,
    the floor could be met by a retriever that answers everything with the whole
    corpus."""

    corpus, cases = load_golden_set(FIXTURE)

    assert len(cases) == 12
    assert len(corpus) >= 12
    assert sum(1 for case in cases if not case["relevant"]) == 2
    assert any(case["language"] != "en" for case in cases), "no multilingual case"
    assert {article["id"] for article in corpus} == {
        article["id"] for article in corpus
    }, "duplicate article ids"


def test_every_label_names_an_article_that_exists() -> None:
    """A mislabelled id would make a relevant document permanently unfindable and read
    as a ranking regression forever."""

    corpus, cases = load_golden_set(FIXTURE)
    known = {article["id"] for article in corpus}

    for case in cases:
        unknown = set(case["relevant"]) - known
        assert not unknown, f"{case['query']!r} labels {unknown}"


def test_the_floor_is_recorded_for_both_modes() -> None:
    """A gate with no committed floor is a dashboard."""

    import json

    floor = json.loads(FIXTURE.read_text())["floor"]

    assert set(floor) == {"lexical", "hybrid"}
    for mode, thresholds in floor.items():
        assert set(thresholds) == {
            "mean_precision_at_5",
            "mean_recall_at_10",
            "mrr",
            "ndcg_at_10",
        }, mode
        assert all(0.0 < value <= 1.0 for value in thresholds.values()), mode


async def test_the_harness_scores_lexical_retrieval_reproducibly(
    pg_session: AsyncSession,
) -> None:
    """The number CI gates on. Deterministic, so two runs of an unchanged ranker cannot
    disagree — a flaky gate is one that gets disabled."""

    corpus, raw_cases = load_golden_set(FIXTURE)
    mapping = await load_corpus(pg_session, corpus)
    cases = resolve_cases(raw_cases, mapping)

    async def search_fn(*, session: AsyncSession, query: str, language: str):
        outcome = await search(
            session, query=query, limit=10, days=7, provider=None, language=language
        )
        return [hit.processed_id for hit in outcome.hits]

    first = await run_evaluation(pg_session, cases=cases, search_fn=search_fn)
    second = await run_evaluation(pg_session, cases=cases, search_fn=search_fn)

    assert first.as_dict() == second.as_dict()
    assert len(first.per_case) == 12
    assert first.mean_recall_at_10 > 0.5, "lexical retrieval found almost nothing"


async def test_a_retriever_that_returns_everything_does_not_pass(
    pg_session: AsyncSession,
) -> None:
    """The failure the two no-answer cases exist to catch.

    Returning the whole corpus maximises recall, so a harness scoring recall alone would
    call this excellent. Precision and the no-answer cases are what stop it.
    """

    corpus, raw_cases = load_golden_set(FIXTURE)
    mapping = await load_corpus(pg_session, corpus)
    cases = resolve_cases(raw_cases, mapping)
    everything = list(mapping.values())

    async def shotgun(*, session: AsyncSession, query: str, language: str):
        return everything[:10]

    report = await run_evaluation(pg_session, cases=cases, search_fn=shotgun)

    assert report.mean_precision_at_5 < 0.29, "the lexical floor would admit a shotgun"
    for case in report.per_case:
        if case.expects_nothing:
            assert case.precision_at_5 == 0.0
            assert case.ndcg_at_10 == 0.0


async def test_a_retriever_that_returns_nothing_does_not_pass(
    pg_session: AsyncSession,
) -> None:
    """The mirror image. Answering nothing gets the two no-answer cases right and
    everything else wrong, which must not average out to a pass."""

    corpus, raw_cases = load_golden_set(FIXTURE)
    mapping = await load_corpus(pg_session, corpus)
    cases = resolve_cases(raw_cases, mapping)

    async def silent(*, session: AsyncSession, query: str, language: str):
        return []

    report = await run_evaluation(pg_session, cases=cases, search_fn=silent)

    assert report.mrr < 0.74, "the lexical floor would admit a retriever that never answers"
    assert report.mean_recall_at_10 < 0.51


async def test_a_perfect_retriever_scores_one(pg_session: AsyncSession) -> None:
    """An oracle that returns exactly the labels, best first, must score 1.0 across the
    board. If it does not, the harness is measuring something other than relevance."""

    corpus, raw_cases = load_golden_set(FIXTURE)
    mapping = await load_corpus(pg_session, corpus)
    cases = resolve_cases(raw_cases, mapping)
    by_query = {case.query: case.relevant for case in cases}

    async def oracle(*, session: AsyncSession, query: str, language: str):
        return list(by_query[query])

    report = await run_evaluation(pg_session, cases=cases, search_fn=oracle)

    assert report.mrr == pytest.approx(1.0)
    assert report.mean_recall_at_10 == pytest.approx(1.0)
    assert report.ndcg_at_10 == pytest.approx(1.0)
    # Not precision: P@5 counts over five slots, and most cases have fewer than five
    # relevant documents, so even an oracle cannot reach 1.0 here.
    assert report.mean_precision_at_5 < 1.0


async def test_a_label_naming_a_missing_article_fails_loudly(
    pg_session: AsyncSession,
) -> None:
    corpus, raw_cases = load_golden_set(FIXTURE)
    mapping = await load_corpus(pg_session, corpus)

    with pytest.raises(ValueError, match="not in the corpus"):
        resolve_cases([{"query": "typo", "language": "en", "relevant": ["a99"]}], mapping)
