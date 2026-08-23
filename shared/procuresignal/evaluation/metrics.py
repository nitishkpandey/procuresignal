"""Retrieval metrics.

Standard definitions, deliberately: the point of an evaluation harness is to produce
numbers comparable with what everyone else means by them, and a house variant of nDCG is
a number only this codebase can interpret.

Every one of these is tested against a worked example computed by hand. Testing a metric
against itself — or against a second implementation written from the same
misunderstanding — is the classic way an evaluation harness certifies a regression as an
improvement.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from math import log2


def precision_at_k(retrieved: Sequence[int], relevant: Collection[int], k: int) -> float:
    """Fraction of the first k results that are relevant.

    Divided by k rather than by how many were returned, following TREC. A system that
    returns two results, both relevant, has not achieved precision@10 of 1.0 — it has
    answered eight fewer times than it was asked to.
    """

    if k <= 0:
        raise ValueError("k must be positive")

    wanted = set(relevant)
    return sum(1 for item in retrieved[:k] if item in wanted) / k


def recall_at_k(retrieved: Sequence[int], relevant: Collection[int], k: int) -> float:
    """Fraction of the relevant documents that appear in the first k results.

    A query with nothing relevant to find scores 1.0: everything there was to find was
    found. The harness does not lean on that — it scores no-result cases explicitly —
    but the alternative here is a division by zero.
    """

    if k <= 0:
        raise ValueError("k must be positive")

    wanted = set(relevant)
    if not wanted:
        return 1.0
    return sum(1 for item in retrieved[:k] if item in wanted) / len(wanted)


def reciprocal_rank(retrieved: Sequence[int], relevant: Collection[int]) -> float:
    """1/rank of the first relevant result, or 0.0 if none is retrieved.

    The metric that cares only about the first correct answer, which is what a user
    scanning a result list actually experiences.
    """

    wanted = set(relevant)
    for rank, item in enumerate(retrieved, start=1):
        if item in wanted:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(
    results: Sequence[tuple[Sequence[int], Collection[int]]],
) -> float:
    """Mean of `reciprocal_rank` over (retrieved, relevant) pairs."""

    if not results:
        return 0.0
    return sum(reciprocal_rank(retrieved, relevant) for retrieved, relevant in results) / len(
        results
    )


def ndcg_at_k(retrieved: Sequence[int], relevant: Collection[int], k: int) -> float:
    """Normalised discounted cumulative gain over binary judgements.

    Gain 1 for a relevant document, discounted by log2(rank + 1), divided by the best
    achievable ordering of the same judgements. Unlike precision it distinguishes a
    relevant result at position 1 from the same result at position 10, which is the
    difference fusion is supposed to make.

    A query with nothing relevant scores 1.0 only when nothing was returned; the ideal
    gain is zero, and returning results anyway is not perfect behaviour.
    """

    if k <= 0:
        raise ValueError("k must be positive")

    wanted = set(relevant)
    if not wanted:
        return 1.0 if not retrieved[:k] else 0.0

    gain = sum(
        1.0 / log2(rank + 1) for rank, item in enumerate(retrieved[:k], start=1) if item in wanted
    )
    ideal = sum(1.0 / log2(rank + 1) for rank in range(1, min(k, len(wanted)) + 1))
    return gain / ideal
