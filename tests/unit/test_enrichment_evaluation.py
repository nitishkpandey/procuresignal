"""Fixed offline pipeline-level quality and call-avoidance gate."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from procuresignal.enrichment import EnrichmentPipeline, EnrichmentPolicy
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "enrichment_evaluation.json"
RECORDINGS_PATH = Path(__file__).parents[1] / "fixtures" / "enrichment_llm_recordings.json"
DIMENSIONS = ("suppliers", "regions", "categories", "signals")


def _set_recall(actual: set[str], expected: set[str]) -> float:
    return 1.0 if not expected else len(actual & expected) / len(expected)


class _RecordedLLM:
    """Offline recorded-output client keyed by article title in the prompt."""

    model = "offline-evaluation"

    def __init__(self, records: list[dict], recordings: list[dict]) -> None:
        self.calls = 0
        self.total_tokens_used = 0
        articles_by_id = {record["id"]: record["article"] for record in records}
        self.outputs = {
            articles_by_id[recording["id"]]["title"]: json.dumps(recording["output"])
            for recording in recordings
        }

    async def call(self, *, user_message: str, **_kwargs) -> str:
        self.calls += 1
        self.total_tokens_used += 100
        return next(output for title, output in self.outputs.items() if title in user_message)

    def get_usage_stats(self) -> dict:
        return {"total_tokens": self.total_tokens_used, "total_calls": self.calls}


@pytest.mark.asyncio
async def test_fixed_fixture_meets_pipeline_cost_and_extraction_quality_gates() -> None:
    records = json.loads(FIXTURE_PATH.read_text())
    recordings = json.loads(RECORDINGS_PATH.read_text())
    assert len(records) >= 20
    assert {item["id"] for item in recordings} == {
        "ambiguous-supplier",
        "ambiguous-region",
        "ambiguous-missing-description",
    }
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 1)

    async with maker() as session:
        raw_rows = []
        for index, record in enumerate(records):
            item = record["article"]
            raw_rows.append(
                NewsArticleRaw(
                    provider=item["provider"],
                    provider_article_id=str(index),
                    query_group=item["query_group"],
                    ingest_hash=f"evaluation-{index}",
                    title=item["title"],
                    description=item.get("description"),
                    content_snippet=item.get("content_snippet"),
                    article_url=f"https://example.test/{index}",
                    source_name=item["source_name"],
                    published_at=now,
                    ingested_at=now,
                    language=item["language"],
                )
            )
        session.add_all(raw_rows)
        await session.commit()

        client = _RecordedLLM(records, recordings)
        result = await EnrichmentPipeline(
            client, policy=EnrichmentPolicy.from_env({})
        ).process_raw_articles(session, raw_rows)
        processed = {
            row.raw_article_id: row
            for row in (await session.scalars(select(NewsArticleProcessed))).all()
        }

        accepted = [
            (record, raw)
            for record, raw in zip(records, raw_rows, strict=True)
            if record["expected_relevance"] == "accepted"
        ]
        # Accepted-candidate avoidance excludes relevance skips by definition.
        avoided_accepted = result.metrics.cached + result.metrics.deterministic
        avoidance_rate = avoided_accepted / len(accepted)
        assert 0.70 <= avoidance_rate <= 0.85
        assert result.metrics.deterministic == 11
        assert result.metrics.cached == 1
        assert result.metrics.llm == 3
        assert result.metrics.llm_calls == client.calls
        assert result.metrics.skipped == len(records) - len(accepted)

        fields = {
            "suppliers": "detected_suppliers",
            "regions": "detected_regions",
            "categories": "detected_categories",
            "signals": "signal_tags",
        }
        for dimension in DIMENSIONS:
            recalls = []
            for record, raw in accepted:
                output = processed[raw.id]
                expected = set(record["baseline"][dimension])
                recalls.append(_set_recall(set(getattr(output, fields[dimension]) or []), expected))
            assert sum(recalls) / len(recalls) >= 0.95, dimension
    await engine.dispose()
