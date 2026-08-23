"""Metrics checked against expectations computed by hand.

Not against a second implementation, and not against themselves. An nDCG that agrees
with its own bug is how an evaluation harness certifies a regression as an improvement,
and this suite is the only thing standing between the search floor and that outcome.

The worked arithmetic is written out in each docstring so a reader can check the expected
value without trusting the code that produced it.
"""

from math import log2

import pytest
from procuresignal.evaluation.metrics import (
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_precision_counts_hits_over_k() -> None:
    """[1, 2, 3, 4] with {2, 4} relevant: two hits in four positions, so 0.5."""

    assert precision_at_k([1, 2, 3, 4], {2, 4}, 4) == pytest.approx(0.5)


def test_precision_only_looks_at_the_first_k() -> None:
    """[1, 2, 3, 4] with {4} relevant, k=2: the hit is at position 4, so 0/2."""

    assert precision_at_k([1, 2, 3, 4], {4}, 2) == pytest.approx(0.0)
    assert precision_at_k([4, 1, 2, 3], {4}, 2) == pytest.approx(0.5)


def test_precision_divides_by_k_not_by_what_was_returned() -> None:
    """Two results, both relevant, at k=5 is 2/5 and not 2/2.

    Returning three fewer answers than asked for is a shortfall, and dividing by the
    length of the result list would score an empty-handed system as perfect.
    """

    assert precision_at_k([1, 2], {1, 2}, 5) == pytest.approx(0.4)


def test_recall_counts_hits_over_what_there_was_to_find() -> None:
    """[1, 2, 3] with {2, 4, 6} relevant: one of three found, so 1/3."""

    assert recall_at_k([1, 2, 3], {2, 4, 6}, 3) == pytest.approx(1 / 3)


def test_recall_reaches_one_when_everything_is_found() -> None:
    assert recall_at_k([5, 1, 9], {1, 5, 9}, 3) == pytest.approx(1.0)


def test_recall_of_nothing_to_find_is_one() -> None:
    """Vacuous rather than a division by zero. The harness scores no-result cases
    explicitly instead of relying on this."""

    assert recall_at_k([1, 2], set(), 5) == pytest.approx(1.0)


def test_reciprocal_rank_is_one_over_the_first_hit() -> None:
    """First relevant result at position 3, so 1/3."""

    assert reciprocal_rank([9, 8, 7, 1], {7, 1}) == pytest.approx(1 / 3)


def test_reciprocal_rank_is_zero_when_nothing_relevant_is_returned() -> None:
    assert reciprocal_rank([9, 8, 7], {1, 2}) == pytest.approx(0.0)


def test_mean_reciprocal_rank_averages_over_queries() -> None:
    """First hit at 1, then at 2, then never: (1 + 0.5 + 0) / 3 = 0.5."""

    cases = [
        ([1, 9], {1}),
        ([9, 2], {2}),
        ([8, 7], {3}),
    ]

    assert mean_reciprocal_rank(cases) == pytest.approx(0.5)


def test_ndcg_discounts_by_position() -> None:
    """[A, B, C, D] = [1, 2, 3, 4] with {2, 4} relevant, k=4.

    DCG  = 1/log2(3) + 1/log2(5) = 0.630930 + 0.430677 = 1.061607
    IDCG = 1/log2(2) + 1/log2(3) = 1.000000 + 0.630930 = 1.630930
    nDCG = 1.061607 / 1.630930 = 0.650920
    """

    assert ndcg_at_k([1, 2, 3, 4], {2, 4}, 4) == pytest.approx(0.650920, abs=1e-6)


def test_ndcg_is_one_for_a_perfect_ordering() -> None:
    """Both relevant documents in the top two positions is the ideal ordering."""

    assert ndcg_at_k([2, 4, 1, 3], {2, 4}, 4) == pytest.approx(1.0)


def test_ndcg_separates_orderings_that_precision_cannot() -> None:
    """The reason nDCG is in the report at all.

    Both lists contain the one relevant document within the top four, so precision@4 is
    0.25 for each. nDCG sees the difference between finding it first and finding it last:

    first:  1/log2(2) = 1.000000, IDCG = 1.000000 -> 1.000000
    last:   1/log2(5) = 0.430677, IDCG = 1.000000 -> 0.430677
    """

    first = ndcg_at_k([7, 1, 2, 3], {7}, 4)
    last = ndcg_at_k([1, 2, 3, 7], {7}, 4)

    assert precision_at_k([7, 1, 2, 3], {7}, 4) == precision_at_k([1, 2, 3, 7], {7}, 4)
    assert first == pytest.approx(1.0)
    assert last == pytest.approx(1 / log2(5), abs=1e-6)
    assert first > last


def test_ndcg_normalises_against_what_was_achievable() -> None:
    """Three relevant documents but only two positions, k=2.

    DCG  = 1/log2(2) + 1/log2(3) = 1.630930
    IDCG = the same, because two is all that fits
    nDCG = 1.0 — the ranker did everything it could within k.
    """

    assert ndcg_at_k([1, 2, 9], {1, 2, 3}, 2) == pytest.approx(1.0)


def test_ndcg_for_a_query_with_no_right_answer() -> None:
    """Perfect only when nothing came back.

    Two of the golden queries are supposed to return nothing, because a system that
    always returns something is not measurably better than one that returns nothing.
    """

    assert ndcg_at_k([], set(), 10) == pytest.approx(1.0)
    assert ndcg_at_k([1, 2], set(), 10) == pytest.approx(0.0)


def test_an_empty_result_list_scores_zero_everywhere_it_should() -> None:
    assert precision_at_k([], {1}, 5) == pytest.approx(0.0)
    assert recall_at_k([], {1}, 5) == pytest.approx(0.0)
    assert reciprocal_rank([], {1}) == pytest.approx(0.0)
    assert ndcg_at_k([], {1}, 5) == pytest.approx(0.0)


def test_mean_reciprocal_rank_of_nothing_is_zero() -> None:
    assert mean_reciprocal_rank([]) == pytest.approx(0.0)


@pytest.mark.parametrize("metric", [precision_at_k, recall_at_k, ndcg_at_k])
def test_k_must_be_positive(metric) -> None:
    """`k=0` would divide by zero in two of these and silently return 0.0 in the third,
    which is worse: a floor computed at k=0 would look like a catastrophic regression."""

    with pytest.raises(ValueError):
        metric([1, 2], {1}, 0)
