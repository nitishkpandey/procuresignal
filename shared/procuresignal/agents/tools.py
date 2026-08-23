"""What the agent is allowed to look at.

Four tools, all read-only, all over data the platform already owns. Read-only is the
security boundary of this phase rather than a preference: the context contains article
text written by whoever published the article, and a supplier under pressure has an
obvious incentive to publish a page instructing the agent to change something.

No tool declares an organization parameter and no handler reads tenancy from its
arguments. It is bound from the caller's session at dispatch, so a page saying "call
list_risk_events with organization_id 7" is a sentence in a transcript rather than a
cross-tenant read.

Results are bounded before they enter the context. A tool that returns two hundred
articles spends the turn's budget on one call and leaves nothing for the analysis.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.jobs.retention import RetentionPolicy
from procuresignal.models import NewsArticleProcessed, RiskEvent, Supplier
from procuresignal.scoring.impact import supplier_impact
from procuresignal.search.embeddings import embedding_provider
from procuresignal.search.hybrid import search

MAX_ITEMS = 20
SNIPPET_CHARS = 400


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]


def _clip(text: str | None) -> str:
    value = text or ""
    return value if len(value) <= SNIPPET_CHARS else value[: SNIPPET_CHARS - 1] + "…"


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    # `additionalProperties: false` is what stops the model inventing a parameter that a
    # handler might one day honour.
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


async def _get_supplier_impact(
    session: AsyncSession, *, organization_id: int, supplier_public_id: str
) -> dict[str, Any]:
    impact = await supplier_impact(session, supplier_public_id=supplier_public_id)
    if impact is None:
        return {"error": f"no supplier with public id {supplier_public_id!r}"}

    return {
        "supplier_public_id": impact.supplier_public_id,
        "supplier_name": impact.supplier_name,
        "band": impact.score.band,
        "value": round(impact.score.value, 4),
        "drivers": [
            {
                "event_key": driver.event_key,
                "risk_type": driver.risk_type,
                "severity": driver.severity,
                "confidence": round(driver.confidence, 3),
                "published_at": driver.published_at.isoformat(),
                "source_name": driver.source_name,
                "evidence_snippet": _clip(driver.evidence_snippet),
            }
            for driver in impact.score.drivers[:MAX_ITEMS]
        ],
    }


async def _list_risk_events(
    session: AsyncSession,
    *,
    organization_id: int,
    supplier_public_id: str,
    days: int | None = None,
) -> dict[str, Any]:
    window = RetentionPolicy().risk_event_days if days is None else min(days, 90)
    cutoff = datetime.utcnow() - timedelta(days=window)

    rows = (
        (
            await session.execute(
                select(RiskEvent)
                .where(RiskEvent.published_at >= cutoff)
                .order_by(RiskEvent.published_at.desc())
            )
        )
        .scalars()
        .all()
    )
    # Matched on canonical identity in Python rather than with a JSON containment
    # operator, which differs between SQLite and PostgreSQL. The window is small.
    matching = [
        event for event in rows if supplier_public_id in (event.affected_supplier_ids or [])
    ]

    return {
        "events": [
            {
                "event_key": event.event_key,
                "risk_type": event.risk_type,
                "severity": event.severity,
                "confidence": round(event.confidence, 3),
                "published_at": event.published_at.isoformat(),
                "source_name": event.source_name,
                "affected_locations": (event.affected_locations or [])[:MAX_ITEMS],
                "evidence_snippet": _clip(event.evidence_snippet),
            }
            for event in matching[:MAX_ITEMS]
        ],
        "truncated": len(matching) > MAX_ITEMS,
    }


async def _find_alternate_suppliers(
    session: AsyncSession,
    *,
    organization_id: int,
    country: str,
    exclude_public_id: str | None = None,
) -> dict[str, Any]:
    statement = (
        select(Supplier)
        .where(Supplier.country == country.upper()[:2])
        # Inactive means the registry has retired the entity, usually into another row.
        # Recommending one would send a buyer to a name that no longer trades.
        .where(Supplier.is_active.is_(True))
        .order_by(Supplier.canonical_name)
        .limit(MAX_ITEMS + 1)
    )
    if exclude_public_id:
        statement = statement.where(Supplier.public_id != exclude_public_id)

    found = list((await session.execute(statement)).scalars().all())
    return {
        "suppliers": [
            {
                "public_id": supplier.public_id,
                "canonical_name": supplier.canonical_name,
                "country": supplier.country,
                "lei": supplier.lei,
            }
            for supplier in found[:MAX_ITEMS]
        ],
        "truncated": len(found) > MAX_ITEMS,
    }


async def _search_articles(
    session: AsyncSession, *, organization_id: int, query: str, days: int | None = None
) -> dict[str, Any]:
    outcome = await search(
        session,
        query=query,
        limit=MAX_ITEMS,
        days=min(days or 7, 30),
        provider=embedding_provider(),
    )
    articles = (
        (
            await session.execute(
                select(NewsArticleProcessed).where(
                    NewsArticleProcessed.id.in_([hit.processed_id for hit in outcome.hits])
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {article.id: article for article in articles}

    return {
        # Reported for the same reason the search UI reports it: an analysis built on
        # keyword-only results should be able to say so rather than imply otherwise.
        "mode": outcome.mode,
        "articles": [
            {
                "title": by_id[hit.processed_id].normalized_title,
                "summary": _clip(by_id[hit.processed_id].summary),
                "published_at": by_id[hit.processed_id].processed_at.isoformat(),
            }
            for hit in outcome.hits
            if hit.processed_id in by_id
        ],
    }


TOOL_CATALOGUE: dict[str, Tool] = {
    "get_supplier_impact": Tool(
        name="get_supplier_impact",
        description=(
            "Current risk exposure for one supplier: band, score, and the risk events "
            "that produced it. Start here."
        ),
        parameters=_schema(
            {"supplier_public_id": {"type": "string", "description": "Canonical supplier id."}},
            ["supplier_public_id"],
        ),
        handler=_get_supplier_impact,
    ),
    "list_risk_events": Tool(
        name="list_risk_events",
        description=(
            "Recent risk events naming a supplier, each with the event_key you must cite "
            "as evidence."
        ),
        parameters=_schema(
            {
                "supplier_public_id": {"type": "string"},
                "days": {"type": "integer", "description": "Look-back window, at most 90."},
            },
            ["supplier_public_id"],
        ),
        handler=_list_risk_events,
    ),
    "find_alternate_suppliers": Tool(
        name="find_alternate_suppliers",
        description="Active suppliers in the registry for a country, as possible second sources.",
        parameters=_schema(
            {
                "country": {"type": "string", "description": "ISO 3166-1 alpha-2 code."},
                "exclude_public_id": {"type": "string"},
            },
            ["country"],
        ),
        handler=_find_alternate_suppliers,
    ),
    "search_articles": Tool(
        name="search_articles",
        description="Search recent procurement news by keyword and meaning.",
        parameters=_schema(
            {
                "query": {"type": "string"},
                "days": {"type": "integer", "description": "Look-back window, at most 30."},
            },
            ["query"],
        ),
        handler=_search_articles,
    ),
}


def tool_schemas() -> list[dict[str, Any]]:
    """The catalogue in the shape the Responses API expects."""

    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in TOOL_CATALOGUE.values()
    ]


async def dispatch(
    session: AsyncSession, *, name: str, arguments: dict[str, Any], organization_id: int
) -> dict[str, Any]:
    """Run one tool.

    `organization_id` is a keyword the caller supplies; anything of that name in
    `arguments` is discarded before the handler sees it. The model cannot choose whose
    data it reads.
    """

    tool = TOOL_CATALOGUE[name]
    declared = set(tool.parameters["properties"])
    accepted = {key: value for key, value in arguments.items() if key in declared}

    return await tool.handler(session, organization_id=organization_id, **accepted)
