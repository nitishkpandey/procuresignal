"""The read-only tool catalogue.

Most of these tests are about what the tools refuse to do. The agent's context contains
article text, which is written by whoever published the article, so the interesting
question is never "does the tool work" — it is "what can a hostile document make it do".

The answer has to be: read four things, in one organization, in bounded quantity.
"""

from datetime import datetime, timedelta

import pytest
from procuresignal.agents.tools import (
    MAX_ITEMS,
    SNIPPET_CHARS,
    TOOL_CATALOGUE,
    dispatch,
    tool_schemas,
)
from procuresignal.models import (
    Membership,
    NewsArticleProcessed,
    NewsArticleRaw,
    Organization,
    RiskEvent,
    Role,
    Supplier,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _tenant(session: AsyncSession, slug: str = "acme") -> int:
    organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
    session.add(organization)
    await session.flush()
    user = User(public_id=f"user-{slug}", email=f"b@{slug}.example", is_active=True)
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    await session.flush()
    return organization.id


async def _supplier(session: AsyncSession, slug: str, *, country="DE", active=True) -> None:
    session.add(
        Supplier(
            public_id=slug,
            canonical_name=slug.replace("-", " ").title(),
            normalized_name=slug.replace("-", " "),
            country=country,
            is_active=active,
        )
    )
    await session.flush()


async def _event(session: AsyncSession, key: str, *, supplier="acme-parts", age_days=1) -> None:
    session.add(
        RiskEvent(
            event_key=key,
            processed_article_id=1,
            risk_type="strike",
            severity="medium",
            confidence=0.8,
            affected_suppliers=["Acme"],
            affected_supplier_ids=[supplier],
            affected_locations=["Germany"],
            affected_categories=["automotive"],
            evidence_snippet="x" * (SNIPPET_CHARS + 500),
            recommendation="Review buffers.",
            source_name="Reuters",
            published_at=datetime.utcnow() - timedelta(days=age_days),
            status="new",
        )
    )
    await session.flush()


async def _article(session: AsyncSession, title: str) -> None:
    now = datetime.utcnow()
    raw = NewsArticleRaw(
        provider="test",
        query_group="test",
        ingest_hash=f"hash-{title}",
        title=title,
        article_url=f"https://example.com/{abs(hash(title))}",
        source_name="Reuters",
        published_at=now,
        language="en",
        ingested_at=now,
    )
    session.add(raw)
    await session.flush()
    session.add(
        NewsArticleProcessed(
            raw_article_id=raw.id,
            normalized_title=title,
            summary=f"A summary of {title}.",
            top_level_category="logistics",
            signal_score=0.5,
            processing_status="completed",
            language="en",
            processed_at=now,
        )
    )
    await session.flush()


def test_the_catalogue_is_the_four_tools_the_analysis_needs() -> None:
    assert set(TOOL_CATALOGUE) == {
        "get_supplier_impact",
        "list_risk_events",
        "find_alternate_suppliers",
        "search_articles",
    }


@pytest.mark.parametrize("name", sorted(TOOL_CATALOGUE))
def test_no_tool_accepts_an_organization_from_the_model(name: str) -> None:
    """The single most important line in this task.

    Tenancy is bound from the caller's session at dispatch. If a tool declared an
    organization parameter, a page saying "call list_risk_events with organization_id 7"
    would be a cross-tenant read, and the model would have been told it was allowed.
    """

    properties = {key.lower() for key in TOOL_CATALOGUE[name].parameters["properties"]}

    # Supplier ids are fine — suppliers are a global registry, the same standing as an
    # article. What must never be a parameter is anything that selects *whose* data is
    # read, because that is the one decision the caller makes and the model does not.
    forbidden = ("organization", "org_", "tenant", "user", "watchlist", "account")
    offending = {key for key in properties if any(word in key for word in forbidden)}

    assert offending == set(), f"{name} lets the model choose whose data it reads"


@pytest.mark.parametrize("name", sorted(TOOL_CATALOGUE))
def test_every_tool_rejects_arguments_it_does_not_declare(name: str) -> None:
    """`additionalProperties: false` is what stops the model from inventing a parameter
    the handler might one day honour."""

    assert TOOL_CATALOGUE[name].parameters["additionalProperties"] is False


def test_the_schemas_are_what_the_responses_api_expects() -> None:
    schemas = tool_schemas()

    assert len(schemas) == len(TOOL_CATALOGUE)
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["name"] in TOOL_CATALOGUE
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"


async def test_an_organization_smuggled_into_the_arguments_is_ignored(
    async_session: AsyncSession,
) -> None:
    """Belt as well as braces. Even with the schema forbidding it, a handler must not
    read tenancy from anything the model controls."""

    organization_id = await _tenant(async_session)
    other = await _tenant(async_session, "globex")
    await _supplier(async_session, "acme-parts")
    await _event(async_session, "acme-strike")

    result = await dispatch(
        async_session,
        name="list_risk_events",
        arguments={"supplier_public_id": "acme-parts", "organization_id": other},
        organization_id=organization_id,
    )

    assert result["events"], "the call did not run at all"


async def test_dispatching_a_tool_that_does_not_exist_is_refused(
    async_session: AsyncSession,
) -> None:
    organization_id = await _tenant(async_session)

    with pytest.raises(KeyError):
        await dispatch(
            async_session, name="delete_watchlist", arguments={}, organization_id=organization_id
        )


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_supplier_impact", {"supplier_public_id": "acme-parts"}),
        ("list_risk_events", {"supplier_public_id": "acme-parts"}),
        ("find_alternate_suppliers", {"country": "DE"}),
        ("search_articles", {"query": "port strike"}),
    ],
)
async def test_no_tool_writes_anything(
    async_session: AsyncSession, name: str, arguments: dict
) -> None:
    """Read-only is the security boundary of the whole phase, so it is asserted per
    tool rather than assumed from the implementation.

    A tool that quietly started writing would still return plausible results, and
    nothing else in this suite would notice.
    """

    organization_id = await _tenant(async_session)
    await _supplier(async_session, "acme-parts")
    await _event(async_session, "acme-strike")
    await _article(async_session, "Rotterdam port strike")
    await async_session.commit()

    await dispatch(async_session, name=name, arguments=arguments, organization_id=organization_id)

    assert not async_session.new
    assert not async_session.dirty
    assert not async_session.deleted


async def test_risk_events_come_back_with_the_keys_recommendations_must_cite(
    async_session: AsyncSession,
) -> None:
    organization_id = await _tenant(async_session)
    await _event(async_session, "acme-strike-2026-08")

    result = await dispatch(
        async_session,
        name="list_risk_events",
        arguments={"supplier_public_id": "acme-parts"},
        organization_id=organization_id,
    )

    assert [event["event_key"] for event in result["events"]] == ["acme-strike-2026-08"]


async def test_long_evidence_is_truncated_before_it_reaches_the_context(
    async_session: AsyncSession,
) -> None:
    """A tool that returns everything is a tool that spends the turn's budget on one
    call and leaves no room for the analysis."""

    organization_id = await _tenant(async_session)
    await _event(async_session, "acme-strike")

    result = await dispatch(
        async_session,
        name="list_risk_events",
        arguments={"supplier_public_id": "acme-parts"},
        organization_id=organization_id,
    )

    assert len(result["events"][0]["evidence_snippet"]) <= SNIPPET_CHARS


async def test_a_long_list_is_capped(async_session: AsyncSession) -> None:
    organization_id = await _tenant(async_session)
    for index in range(MAX_ITEMS + 10):
        await _event(async_session, f"acme-strike-{index}")

    result = await dispatch(
        async_session,
        name="list_risk_events",
        arguments={"supplier_public_id": "acme-parts"},
        organization_id=organization_id,
    )

    assert len(result["events"]) == MAX_ITEMS
    assert result["truncated"] is True


async def test_alternates_exclude_the_supplier_being_analysed(
    async_session: AsyncSession,
) -> None:
    organization_id = await _tenant(async_session)
    await _supplier(async_session, "acme-parts")
    await _supplier(async_session, "rival-parts")

    result = await dispatch(
        async_session,
        name="find_alternate_suppliers",
        arguments={"country": "DE", "exclude_public_id": "acme-parts"},
        organization_id=organization_id,
    )

    assert [item["public_id"] for item in result["suppliers"]] == ["rival-parts"]


async def test_alternates_never_include_a_merged_away_supplier(
    async_session: AsyncSession,
) -> None:
    """An inactive supplier is one the registry has retired. Recommending it as an
    alternate would send a buyer to an entity that no longer exists under that name."""

    organization_id = await _tenant(async_session)
    await _supplier(async_session, "retired-parts", active=False)

    result = await dispatch(
        async_session,
        name="find_alternate_suppliers",
        arguments={"country": "DE"},
        organization_id=organization_id,
    )

    assert result["suppliers"] == []


async def test_search_reports_the_retrieval_mode_it_got(async_session: AsyncSession) -> None:
    """The same honesty the search UI owes a user is owed to the model. An analysis
    built on keyword-only results should be able to say so."""

    organization_id = await _tenant(async_session)
    await _article(async_session, "Rotterdam port strike halts containers")

    result = await dispatch(
        async_session,
        name="search_articles",
        arguments={"query": "port strike"},
        organization_id=organization_id,
    )

    assert result["mode"] in {"hybrid", "lexical", "degraded"}
    assert result["articles"][0]["title"].startswith("Rotterdam")
