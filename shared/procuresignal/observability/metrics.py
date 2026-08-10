"""Prometheus metrics and the middleware that populates them.

Shared by the API and the workers. It previously lived under `api`, which the worker
image does not copy, so importing it from a task made the worker container fail to
start — and no test caught it because tests import from the source tree.

`prometheus.yml` has scraped `api:8000/metrics` since before any of this existed, so the
scrape has been failing the whole time. Monitoring configured against nothing looks the
same from the outside as monitoring that works, which is exactly the class of failure
this is meant to reveal.
"""

import logging
import time

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match, Route

logger = logging.getLogger(__name__)


def _ensure_multiprocess_dir() -> None:
    """Create the multiprocess directory before any metric is defined.

    prometheus_client writes its per-process files the moment a metric is constructed,
    and raises if the directory is missing. Setting the variable without creating the
    path made every process that imports this module fail at import — which is how the
    worker container died on start.
    """

    import os
    from pathlib import Path

    directory = os.getenv("PROMETHEUS_MULTIPROC_DIR")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)


_ensure_multiprocess_dir()

NAMESPACE = "procuresignal"

# Path is the route template, never the resolved URL. A label per article id is
# unbounded cardinality: a crawler walking ids would grow the metric set until the
# Prometheus server fell over.
HTTP_REQUESTS = Counter(
    f"{NAMESPACE}_http_requests_total",
    "HTTP requests handled, by route template.",
    ["method", "path", "status"],
)

HTTP_LATENCY = Histogram(
    f"{NAMESPACE}_http_request_seconds",
    "Time to handle a request, by route template.",
    ["method", "path"],
)

RETRIEVAL_ARTICLES = Counter(
    f"{NAMESPACE}_retrieval_articles_total",
    "Articles seen during retrieval, by source and outcome.",
    ["source_id", "outcome"],
)

ENRICHMENT_LLM_CALLS = Counter(
    f"{NAMESPACE}_enrichment_llm_calls_total",
    "LLM calls attempted during enrichment, by outcome.",
    ["outcome"],
)

# The one that matters. A stage that stops producing leaves this gauge frozen while
# every health check stays green, which is how ingestion returns nothing for days
# without anyone noticing. Task 3's staleness alert reads it.
PIPELINE_LAST_SUCCESS = Gauge(
    f"{NAMESPACE}_pipeline_last_success_timestamp",
    "Unix time of the last successful run of a pipeline stage.",
    ["stage"],
    # Whichever child process ran the stage most recently is the answer. Without this
    # the collector would sum timestamps across processes, which is meaningless.
    multiprocess_mode="max",
)

# A queue quietly filling with poison is worth paging on: the work is lost and the
# system keeps reporting healthy.
DEAD_LETTERS = Counter(
    f"{NAMESPACE}_dead_letters_total",
    "Tasks that exhausted their retries, by task name.",
    ["task"],
)

# A tenant hitting its cap is a product signal, not just an operational one:
# somebody is either ingesting far more than expected or looping.
LLM_BUDGET_REFUSALS = Counter(
    f"{NAMESPACE}_llm_budget_refusals_total",
    "LLM calls refused because a tenant was over its daily budget.",
    ["tenant"],
)

# Falling open is deliberate, but it must not be silent: a limiter that is quietly
# not limiting is worse than none, because it is believed.
RATE_LIMIT_BACKEND_ERRORS = Counter(
    f"{NAMESPACE}_rate_limit_backend_errors_total",
    "Times the shared rate-limit backend was unreachable and the limiter fell open.",
)

# Screening coverage is the compliance-relevant number. A control that quietly
# places nothing looks exactly like one that is working.
SANCTIONS_SCREENING = Counter(
    f"{NAMESPACE}_sanctions_screening_total",
    "Sanctions designation names screened, by whether they matched a supplier.",
    ["outcome"],
)

# A drain that stalls leaves alerts queued while every other signal looks healthy,
# which is the quiet version of not alerting at all.
NOTIFICATIONS_PENDING = Gauge(
    f"{NAMESPACE}_notifications_pending",
    "Alerts queued in the outbox and not yet delivered.",
    multiprocess_mode="max",
)

METRICS_PATH = "/metrics"

# Requests that match no route are all recorded under one label. Without this, anything
# probing random URLs could grow the metric set at will.
UNMATCHED_PATH = "<unmatched>"


def route_template(request: Request) -> str:
    """The registered path pattern for a request, or a single shared label.

    The application is read from the request scope rather than from what was handed to
    the middleware: `add_middleware` passes the next app in the chain, which is another
    middleware and has no routing table.
    """

    app = request.scope.get("app")
    for route in getattr(app, "routes", []):
        if isinstance(route, Route):
            match, _ = route.matches(request.scope)
            if match is not Match.NONE:
                return route.path
    return UNMATCHED_PATH


def record_pipeline_success(stage: str, *, at: float | None = None) -> None:
    """Mark a pipeline stage as having just succeeded."""

    PIPELINE_LAST_SUCCESS.labels(stage=stage).set(at if at is not None else time.time())


def record_dead_letter_metric(task: str) -> None:
    DEAD_LETTERS.labels(task=task).inc()


def record_budget_refusal(tenant: str) -> None:
    LLM_BUDGET_REFUSALS.labels(tenant=tenant).inc()


def record_rate_limit_backend_error() -> None:
    RATE_LIMIT_BACKEND_ERRORS.inc()


def record_screening(outcome: str, count: int = 1) -> None:
    if count:
        SANCTIONS_SCREENING.labels(outcome=outcome).inc(count)


def record_outbox_depth(pending: int) -> None:
    NOTIFICATIONS_PENDING.set(pending)


def record_retrieval(source_id: str, outcome: str, count: int = 1) -> None:
    RETRIEVAL_ARTICLES.labels(source_id=source_id, outcome=outcome).inc(count)


def record_llm_call(outcome: str, count: int = 1) -> None:
    ENRICHMENT_LLM_CALLS.labels(outcome=outcome).inc(count)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Count and time every request against its route template."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        # The scrape does not count itself; otherwise the request rate becomes a
        # function of the scrape interval rather than of real traffic.
        if request.url.path == METRICS_PATH:
            return await call_next(request)

        path = route_template(request)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            HTTP_REQUESTS.labels(method=request.method, path=path, status="500").inc()
            raise

        HTTP_REQUESTS.labels(
            method=request.method, path=path, status=str(response.status_code)
        ).inc()
        HTTP_LATENCY.labels(method=request.method, path=path).observe(time.perf_counter() - started)
        return response


def metrics_response() -> Response:
    """Render the registry in Prometheus text format.

    Deliberately unauthenticated: Prometheus scrapes from inside the compose network and
    holds no credential. Nothing here carries request bodies, headers, or identifiers —
    only counts against bounded labels.
    """

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = [
    "NAMESPACE",
    "METRICS_PATH",
    "UNMATCHED_PATH",
    "HTTP_REQUESTS",
    "HTTP_LATENCY",
    "RETRIEVAL_ARTICLES",
    "ENRICHMENT_LLM_CALLS",
    "PIPELINE_LAST_SUCCESS",
    "DEAD_LETTERS",
    "LLM_BUDGET_REFUSALS",
    "RATE_LIMIT_BACKEND_ERRORS",
    "SANCTIONS_SCREENING",
    "MetricsMiddleware",
    "metrics_response",
    "route_template",
    "record_pipeline_success",
    "record_retrieval",
    "record_llm_call",
    "record_dead_letter_metric",
    "record_budget_refusal",
    "record_rate_limit_backend_error",
    "record_screening",
    "NOTIFICATIONS_PENDING",
    "record_outbox_depth",
    "start_worker_metrics_server",
]


def start_worker_metrics_server(port: int | None = None) -> None:
    """Expose this process's metrics over HTTP.

    Celery workers serve no HTTP of their own, so every counter they publish —
    retrieval outcomes, enrichment spend, dead letters, sanctions screening — was
    invisible: Prometheus only ever scraped the API. Most of what is worth alerting on
    is produced here.

    Prefork means task bodies run in child processes, so PROMETHEUS_MULTIPROC_DIR must
    be set for their counters to reach the parent that serves this endpoint. Without it
    only the parent's own metrics appear, which is quietly wrong rather than loudly
    broken, so it is checked.
    """

    import os

    from prometheus_client import CollectorRegistry, multiprocess, start_http_server

    listen_on = port or int(os.getenv("WORKER_METRICS_PORT", "9101"))

    if not os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        logger.warning(
            "PROMETHEUS_MULTIPROC_DIR is unset; child-process metrics will not be "
            "collected and worker counters will read as zero"
        )
        start_http_server(listen_on)
        return

    # Prefork runs task bodies in child processes, each writing its own files. The
    # default registry only sees this process, so serving it would report near-zero
    # while the work happened elsewhere — which reads as a quiet system rather than a
    # misconfigured one. The multiprocess collector aggregates across all of them.
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(listen_on, registry=registry)
