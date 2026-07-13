"""Populated data-migration test for processed-article consolidation."""

import importlib
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


def _prior_schema(metadata: sa.MetaData) -> tuple[sa.Table, list[sa.Table]]:
    processed = sa.Table(
        "news_articles_processed",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("raw_article_id", sa.Integer, nullable=False),
        sa.Column("normalized_title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("top_level_category", sa.String(50), nullable=False),
        sa.Column("signal_tags", sa.JSON),
        sa.Column("priority_signal", sa.String(100)),
        sa.Column("detected_regions", sa.JSON),
        sa.Column("detected_suppliers", sa.JSON),
        sa.Column("detected_categories", sa.JSON),
        sa.Column("signal_score", sa.Float, nullable=False),
        sa.Column("processing_status", sa.String(20), nullable=False),
        sa.Column("llm_model", sa.String(100)),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("processed_at", sa.DateTime, nullable=False),
        sa.Column("risk_event_checked_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    dependents = []
    for name in ("news_article_matches", "news_priority_events", "user_news_feed"):
        dependents.append(
            sa.Table(
                name,
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("processed_article_id", sa.Integer, nullable=False),
            )
        )
    dependents.append(
        sa.Table(
            "risk_events",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("event_key", sa.String(500), nullable=False, unique=True),
            sa.Column("processed_article_id", sa.Integer, nullable=False),
        )
    )
    return processed, dependents


def _row(row_id: int, *, status: str, when: datetime, rich: bool) -> dict:
    return {
        "id": row_id,
        "raw_article_id": 42,
        "normalized_title": f"row-{row_id}",
        "summary": f"summary-{row_id}",
        "top_level_category": "general",
        "signal_tags": ["tariff"] if rich else None,
        "priority_signal": "tariff" if rich else None,
        "detected_regions": ["Germany"] if rich else None,
        "detected_suppliers": ["Bosch"] if rich else None,
        "detected_categories": ["automotive"] if rich else None,
        "signal_score": 0.8 if rich else 0.1,
        "processing_status": status,
        "llm_model": "openai/test" if rich else None,
        "language": "en",
        "processed_at": when,
        "risk_event_checked_at": when if rich else None,
        "created_at": when,
        "updated_at": when,
    }


def test_populated_upgrade_repoints_all_dependents_and_downgrades(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    processed, dependents = _prior_schema(metadata)
    metadata.create_all(engine)
    now = datetime.utcnow()
    with engine.begin() as connection:
        connection.execute(
            processed.insert(),
            [
                _row(1, status="failed", when=now + timedelta(days=3), rich=True),
                _row(2, status="completed", when=now, rich=False),
                _row(3, status="completed", when=now + timedelta(days=1), rich=True),
            ],
        )
        for index, table in enumerate(dependents):
            rows = [
                {"id": index * 10 + 1, "processed_article_id": 1},
                {"id": index * 10 + 2, "processed_article_id": 2},
                {"id": index * 10 + 3, "processed_article_id": 3},
            ]
            if table.name == "risk_events":
                for offset, row in enumerate(rows):
                    row["event_key"] = f"event-{offset}"
            connection.execute(table.insert(), rows)

        migration = importlib.import_module(
            "migrations.versions.f6a7b8_add_enrichment_routing_cache"
        )
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()

        survivors = connection.execute(
            sa.text(
                "SELECT id, normalized_title FROM news_articles_processed WHERE raw_article_id = 42"
            )
        ).all()
        assert survivors == [(3, "row-3")]
        for table in dependents:
            ids = (
                connection.execute(
                    sa.text(f"SELECT processed_article_id FROM {table.name} ORDER BY id")
                )
                .scalars()
                .all()
            )
            assert ids == [3, 3, 3]
        with pytest.raises(IntegrityError):
            connection.execute(
                processed.insert(),
                _row(4, status="completed", when=now + timedelta(days=4), rich=True),
            )

        migration.downgrade()
        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("news_articles_processed")
        }
        assert "enrichment_method" not in columns
        assert not sa.inspect(connection).has_table("enrichment_cache")
        connection.execute(
            processed.insert(), _row(4, status="completed", when=now + timedelta(days=4), rich=True)
        )
