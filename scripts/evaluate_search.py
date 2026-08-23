#!/usr/bin/env python
"""Score retrieval against the golden set and fail if it has regressed.

A gate, not a dashboard. Below the floor committed alongside the labels, this exits
non-zero and the build stops.

By default it evaluates lexical retrieval only, which is what CI can run: hybrid
retrieval needs an embedding provider, and a build that spends money on every push and
depends on a third party being up is a build that gets disabled. `--hybrid` evaluates the
full stack locally, where a key is configured.

The floor is therefore a lexical floor, and the report says so. A lexical number
presented as if the whole system had been measured is the kind of quiet dishonesty an
evaluation harness exists to prevent.
"""

# The imports below follow a sys.path setup so the script runs directly from a checkout
# as well as under `poetry run`, which is what CI uses.
# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "shared")]

from procuresignal.evaluation.harness import (
    EvaluationReport,
    load_corpus,
    load_golden_set,
    resolve_cases,
    run_evaluation,
)
from procuresignal.search.embeddings import embed_pending_articles, embedding_provider
from procuresignal.search.hybrid import search
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

FIXTURE = ROOT / "tests" / "fixtures" / "golden_queries.json"
# Wide enough that recall@10 can reach 1.0, so the metric measures the ranker rather
# than the page size.
RETRIEVAL_LIMIT = 10
# The corpus is created with timestamps a few minutes apart, so any window covers it.
SEARCH_DAYS = 7


def _admin_url(url: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/postgres"


def _with_database(url: str, name: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


async def _run_admin(url: str, *statements: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


async def evaluate(database_url: str, *, hybrid: bool) -> tuple[EvaluationReport, str]:
    """Build a throwaway database, load the golden corpus, and score retrieval.

    Throwaway rather than the caller's database because the corpus has to be exactly the
    twelve queries' worth of articles and nothing else: evaluating against whatever
    happens to be ingested would produce a number that moves for reasons unrelated to
    the ranker.
    """

    name = f"evaluation_{uuid.uuid4().hex[:12]}"
    admin = _admin_url(database_url)
    await _run_admin(admin, f'CREATE DATABASE "{name}"')
    target = _with_database(database_url, name)

    try:
        migrate = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": target},
            capture_output=True,
            text=True,
            timeout=300,
        )
        if migrate.returncode != 0:
            raise SystemExit(f"alembic upgrade failed:\n{migrate.stdout}\n{migrate.stderr}")

        corpus, raw_cases = load_golden_set(FIXTURE)
        engine = create_async_engine(target)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with maker() as session:
                mapping = await load_corpus(session, corpus)
                cases = resolve_cases(raw_cases, mapping)

                provider = embedding_provider() if hybrid else None
                if hybrid:
                    if provider is None:
                        raise SystemExit(
                            "--hybrid needs an embedding provider; OPENAI_API_KEY is unset"
                        )
                    await embed_pending_articles(session, provider=provider)

                async def search_fn(*, session: AsyncSession, query: str, language: str):
                    outcome = await search(
                        session,
                        query=query,
                        limit=RETRIEVAL_LIMIT,
                        days=SEARCH_DAYS,
                        provider=provider,
                        language=language,
                    )
                    return [hit.processed_id for hit in outcome.hits]

                report = await run_evaluation(session, cases=cases, search_fn=search_fn)
                mode = "hybrid" if hybrid else "lexical"
                return report, mode
        finally:
            await engine.dispose()
    finally:
        await _run_admin(
            admin,
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{name}' AND pid <> pg_backend_pid()",
            f'DROP DATABASE IF EXISTS "{name}"',
        )


def render(report: EvaluationReport, mode: str) -> None:
    print(f"\nRetrieval evaluation — {mode}\n")
    print(f"  {'query':<40} {'P@5':>6} {'R@10':>6} {'RR':>6} {'nDCG':>6}")
    print(f"  {'-' * 68}")
    for case in report.per_case:
        marker = " *" if case.expects_nothing else "  "
        print(
            f"  {case.query[:38]:<38}{marker} {case.precision_at_5:>6.3f} "
            f"{case.recall_at_10:>6.3f} {case.reciprocal_rank:>6.3f} {case.ndcg_at_10:>6.3f}"
        )
    print(f"  {'-' * 68}")
    print(
        f"  {'mean':<40} {report.mean_precision_at_5:>6.3f} "
        f"{report.mean_recall_at_10:>6.3f} {report.mrr:>6.3f} {report.ndcg_at_10:>6.3f}"
    )
    print("\n  * correct answer is no results\n")


def check_floor(report: EvaluationReport, floor: dict[str, float]) -> list[str]:
    return [
        f"{metric}: {report.as_dict()[metric]:.4f} is below the floor of {minimum:.4f}"
        for metric, minimum in floor.items()
        if report.as_dict()[metric] < minimum
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="PostgreSQL server to create the throwaway evaluation database on.",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="Embed the corpus and evaluate lexical plus semantic retrieval.",
    )
    parser.add_argument(
        "--no-floor", action="store_true", help="Report without enforcing the floor."
    )
    arguments = parser.parse_args()

    if not arguments.database_url:
        print("no database: set TEST_DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2

    report, mode = asyncio.run(evaluate(arguments.database_url, hybrid=arguments.hybrid))
    render(report, mode)

    if arguments.no_floor:
        return 0

    floors = json.loads(FIXTURE.read_text()).get("floor", {})
    floor = floors.get(mode, {})
    if not floor:
        print(f"no floor recorded for {mode} retrieval", file=sys.stderr)
        return 2

    failures = check_floor(report, floor)
    if failures:
        print("RETRIEVAL HAS REGRESSED", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print(
            "\nThe floor lives in tests/fixtures/golden_queries.json. It moves up when "
            "retrieval improves; lowering it needs a note in the phase plan saying why.",
            file=sys.stderr,
        )
        return 1

    print(f"  floor met for {mode} retrieval\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
