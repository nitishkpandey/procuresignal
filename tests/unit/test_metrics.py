"""Tests for the metrics endpoint and instrumentation.

prometheus.yml has scraped api:8000/metrics since before any of this work, and the
endpoint never existed. A configured scrape against nothing looks the same from the
outside as a healthy system, which is the failure this task removes.
"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import Base, Role
from procuresignal.observability.metrics import (
    ENRICHMENT_LLM_CALLS,
    HTTP_REQUESTS,
    PIPELINE_LAST_SUCCESS,
    RETRIEVAL_ARTICLES,
    record_pipeline_success,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_current_user, get_session
from api.main import app
from tests.conftest import fixed_identity


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    async def _session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: fixed_identity("u1", role=Role.OWNER)

    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _scrape(client: TestClient) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    return response.text


def test_metrics_endpoint_is_served(client: TestClient) -> None:
    assert "procuresignal_http_requests_total" in _scrape(client)


def test_metrics_are_readable_without_credentials(client: TestClient) -> None:
    """Prometheus scrapes inside the compose network and holds no token."""
    app.dependency_overrides.pop(get_current_user, None)

    assert client.get("/metrics").status_code == 200


def test_requests_are_counted_by_route(client: TestClient) -> None:
    client.get("/api/feed")
    client.get("/api/feed")

    body = _scrape(client)
    assert 'path="/api/feed"' in body
    assert 'method="GET"' in body


def test_paths_are_templated_rather_than_per_id(client: TestClient) -> None:
    """Per-id labels are unbounded cardinality and will take the Prometheus server down."""
    for article_id in range(5):
        client.get(f"/api/articles/{article_id}")

    body = _scrape(client)
    assert 'path="/api/articles/{article_id}"' in body
    for article_id in range(5):
        assert f'path="/api/articles/{article_id}"' not in body


def test_unmatched_paths_do_not_create_a_label_per_url(client: TestClient) -> None:
    """A scanner hitting random URLs must not be able to grow the metric set."""
    for suffix in ("wp-admin", "phpmyadmin", ".env"):
        client.get(f"/{suffix}")

    body = _scrape(client)
    assert "wp-admin" not in body
    assert "phpmyadmin" not in body


def test_status_codes_are_recorded(client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user, None)
    client.get("/api/feed")

    assert 'status="401"' in _scrape(client)


def test_metrics_never_expose_credentials(client: TestClient) -> None:
    client.get("/api/feed", headers={"Authorization": "Bearer super-secret-token"})

    body = _scrape(client)
    assert "super-secret-token" not in body
    assert "Bearer" not in body
    assert "procuresignal_refresh" not in body


def test_the_metrics_endpoint_does_not_count_itself(client: TestClient) -> None:
    """Self-counting makes the request rate a function of the scrape interval."""
    _scrape(client)
    _scrape(client)

    assert 'path="/metrics"' not in _scrape(client)


def test_pipeline_freshness_is_published() -> None:
    """Task 3's staleness alert is built on this, and it is what catches silent stalls."""
    record_pipeline_success("retrieval")

    value = PIPELINE_LAST_SUCCESS.labels(stage="retrieval")._value.get()
    assert value > 0


def test_the_metrics_alerting_depends_on_all_exist() -> None:
    """A rule naming a metric nobody publishes never fires and looks like health."""
    for metric in (HTTP_REQUESTS, RETRIEVAL_ARTICLES, ENRICHMENT_LLM_CALLS, PIPELINE_LAST_SUCCESS):
        assert metric is not None


def test_metric_names_are_namespaced(client: TestClient) -> None:
    body = _scrape(client)

    for name in (
        "procuresignal_http_requests_total",
        "procuresignal_pipeline_last_success_timestamp",
    ):
        assert name in body


def test_every_pipeline_stage_reports_freshness() -> None:
    """A gauge nobody populates is the same blind spot as no gauge at all."""
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "worker" / "tasks.py"
    recorded = set(re.findall(r'record_pipeline_success\("([a-z_]+)"\)', source.read_text()))

    assert recorded == {
        "retrieval",
        "normalization",
        "enrichment",
        "personalization",
        "risk_events",
        "sanctions_screening",
        "supplier_resolution",
    }


def test_retrieval_freshness_is_conditional_on_completion() -> None:
    """A partial run marking itself fresh would hide the stall being watched for."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "worker" / "tasks.py").read_text()
    guarded = 'if result.status == "completed":\n            record_pipeline_success("retrieval")'

    assert guarded in source
