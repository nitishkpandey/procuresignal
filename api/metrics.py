"""Prometheus metrics and the middleware that populates them.

`prometheus.yml` has scraped `api:8000/metrics` since before any of this existed, so the
scrape has been failing the whole time. Monitoring configured against nothing looks the
same from the outside as monitoring that works, which is exactly the class of failure
this is meant to reveal.
"""

import time

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match, Route

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
