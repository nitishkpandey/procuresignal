"""Screening has to be auditable and measurable, not just correct.

A compliance control that runs and reports nothing is indistinguishable from one that
is switched off. These were recorded as gaps when Phase 3a shipped and left open.
"""

from pathlib import Path

import pytest
import yaml
from procuresignal.models import AuditLog, NewsArticleProcessed, NewsArticleRaw
from procuresignal.suppliers.registry import add_alias, register_supplier
from procuresignal.suppliers.screening import screen_processed_articles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def designation(async_session: AsyncSession):
    supplier = await register_supplier(async_session, canonical_name="Siemens AG")
    await add_alias(async_session, supplier_id=supplier.id, alias="Siemens Aktiengesellschaft")

    from datetime import datetime

    raw = NewsArticleRaw(
        provider="eu_sanctions",
        provider_article_id="eu-sanctions:d1",
        query_group="sanctions",
        ingest_hash="d1",
        title="EU sanctions designation",
        description="Entity",
        content_snippet="Entity",
        article_url="https://webgate.ec.europa.eu/fsd",
        source_name="DG FISMA",
        published_at=datetime(2026, 8, 1),
        ingested_at=datetime(2026, 8, 1),
        language="en",
        raw_payload_json={
            "designation_id": "d1",
            "designation_names": ["Siemens Aktiengesellschaft", "Totally Unknown Entity"],
        },
    )
    async_session.add(raw)
    await async_session.flush()
    async_session.add(
        NewsArticleProcessed(
            raw_article_id=raw.id,
            normalized_title=raw.title,
            summary=raw.description,
            top_level_category="regulatory",
            signal_tags=["sanctions"],
            priority_signal="sanctions",
            detected_suppliers=[],
            detected_regions=[],
            detected_categories=["regulatory"],
            processed_at=datetime(2026, 8, 1),
        )
    )
    await async_session.commit()
    return supplier


async def test_a_screening_run_is_audited(async_session: AsyncSession, designation) -> None:
    """Who was flagged, and when, is exactly what an auditor asks for."""
    await screen_processed_articles(async_session)

    rows = (await async_session.execute(select(AuditLog))).scalars().all()
    actions = {row.action for row in rows}

    assert "sanctions.screening_run" in actions


async def test_a_supplier_match_is_audited_individually(
    async_session: AsyncSession, designation
) -> None:
    """A run summary says how many matched; the control needs to say which."""
    await screen_processed_articles(async_session)

    rows = (await async_session.execute(select(AuditLog))).scalars().all()
    matches = [row for row in rows if row.action == "sanctions.supplier_flagged"]

    assert matches
    assert matches[0].resource_id == designation.public_id


async def test_the_audit_records_what_could_not_be_placed(
    async_session: AsyncSession, designation
) -> None:
    """Coverage is the compliance-relevant number, so it belongs in the trail."""
    await screen_processed_articles(async_session)

    rows = (await async_session.execute(select(AuditLog))).scalars().all()
    run = next(row for row in rows if row.action == "sanctions.screening_run")

    assert run.detail["unmatched_names"] == 1
    assert run.detail["suppliers_flagged"] == 1


async def test_screening_publishes_metrics(async_session: AsyncSession, designation) -> None:
    from procuresignal.observability.metrics import SANCTIONS_SCREENING

    before = SANCTIONS_SCREENING.labels(outcome="matched")._value.get()
    await screen_processed_articles(async_session)

    assert SANCTIONS_SCREENING.labels(outcome="matched")._value.get() > before
    assert SANCTIONS_SCREENING.labels(outcome="unmatched")._value.get() > 0


def test_an_alert_watches_screening_coverage() -> None:
    """Screening that quietly places nothing looks exactly like screening that works."""
    document = yaml.safe_load((ROOT / "docker/prometheus/alerts.yml").read_text())
    alerts = {rule["alert"] for group in document["groups"] for rule in group["rules"]}

    assert "SanctionsScreeningUnplaced" in alerts
