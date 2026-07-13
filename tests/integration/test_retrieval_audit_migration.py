"""Populated migration coverage for retrieval provenance and audit tables."""

import importlib
from datetime import datetime

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_populated_retrieval_audit_upgrade_and_downgrade(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    raw = sa.Table(
        "news_articles_raw", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(raw.insert(), {"id": 7, "title": "legacy"})
        migration = importlib.import_module(
            "migrations.versions.f8c9d0_add_retrieval_source_audit"
        )
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()
        row = connection.execute(sa.text(
            "SELECT source_id, source_domains, source_countries, registry_version, "
            "retrieved_at, source_published_at_raw FROM news_articles_raw WHERE id=7"
        )).one()
        assert row.source_id is None
        assert row.source_domains is None
        assert row.source_countries is None
        assert row.registry_version is None
        assert row.retrieved_at is None
        assert row.source_published_at_raw is None
        connection.execute(sa.text(
            "INSERT INTO news_retrieval_runs "
            "(run_key,status,registry_version,started_at,created_at,updated_at) "
            "VALUES ('run-1','running','v1',:now,:now,:now)"
        ), {"now": datetime.utcnow()})
        run_id = connection.execute(sa.text(
            "SELECT id FROM news_retrieval_runs WHERE run_key='run-1'"
        )).scalar_one()
        connection.execute(sa.text(
            "INSERT INTO news_retrieval_source_outcomes "
            "(run_id,source_id,status,attempted_count,fetched_count,accepted_count,"
            "inserted_count,duplicate_count,rejected_count,failed_count,created_at,updated_at) "
            "VALUES (:run_id,'ecb','success',1,1,1,1,0,0,0,:now,:now)"
        ), {"run_id": run_id, "now": datetime.utcnow()})
        migration.downgrade()
        assert connection.execute(sa.text(
            "SELECT title FROM news_articles_raw WHERE id=7"
        )).scalar_one() == "legacy"
        assert not sa.inspect(connection).has_table("news_retrieval_runs")
        assert "source_id" not in {
            col["name"] for col in sa.inspect(connection).get_columns("news_articles_raw")
        }
