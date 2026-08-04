"""Tests for supplier name resolution."""

import pytest
from procuresignal.suppliers.registry import add_alias, register_supplier
from procuresignal.suppliers.resolver import resolve, resolve_many
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def registry(async_session: AsyncSession):
    siemens = await register_supplier(async_session, canonical_name="Siemens AG", country="DE")
    energy = await register_supplier(
        async_session, canonical_name="Siemens Energy AG", country="DE"
    )
    bosch = await register_supplier(async_session, canonical_name="Robert Bosch GmbH", country="DE")
    await add_alias(async_session, supplier_id=bosch.id, alias="Bosch")
    await async_session.flush()
    return {"siemens": siemens, "energy": energy, "bosch": bosch}


@pytest.mark.parametrize(
    "surface",
    ["Siemens AG", "siemens ag", "  SIEMENS   AG ", "Siemens", "Siemens, AG.", "siemens"],
)
async def test_spelling_variants_resolve_to_one_entity(
    async_session: AsyncSession, registry, surface: str
) -> None:
    """This is the miss the phase exists to fix."""
    resolution = await resolve(async_session, surface)

    assert resolution.supplier_id == registry["siemens"].id
    assert resolution.public_id == registry["siemens"].public_id
    assert resolution.confidence == 1.0


async def test_a_spinoff_does_not_resolve_to_its_parent(
    async_session: AsyncSession, registry
) -> None:
    """Siemens Energy carries different risk and must stay separate."""
    resolution = await resolve(async_session, "Siemens Energy AG")

    assert resolution.supplier_id == registry["energy"].id
    assert resolution.supplier_id != registry["siemens"].id


async def test_manual_alias_resolves(async_session: AsyncSession, registry) -> None:
    assert (await resolve(async_session, "Bosch")).supplier_id == registry["bosch"].id
    assert (await resolve(async_session, "Robert Bosch GmbH")).supplier_id == registry["bosch"].id


async def test_unknown_name_is_unresolved_not_guessed(
    async_session: AsyncSession, registry
) -> None:
    resolution = await resolve(async_session, "Some Company Nobody Registered")

    assert resolution.supplier_id is None
    assert resolution.public_id is None
    assert resolution.confidence == 0.0
    assert resolution.surface_form == "Some Company Nobody Registered"


@pytest.mark.parametrize(
    "noise",
    ["cabbage", "3m-long delay", "Captive insurance", "siemens announced", "the siemens"],
)
async def test_partial_and_surrounding_text_does_not_resolve(
    async_session: AsyncSession, registry, noise: str
) -> None:
    """Resolution is exact on the whole normalized name.

    The old matcher found 'ABB' inside 'cabbage'. An exact alias lookup cannot, and
    neither can a name with extra words around it.
    """
    assert (await resolve(async_session, noise)).supplier_id is None


@pytest.mark.parametrize("blank", ["", "   ", "..."])
async def test_blank_surface_forms_are_unresolved(
    async_session: AsyncSession, registry, blank: str
) -> None:
    assert (await resolve(async_session, blank)).supplier_id is None


async def test_inactive_suppliers_do_not_resolve(async_session: AsyncSession, registry) -> None:
    """A merged-away supplier must stop answering for its old name."""
    registry["energy"].is_active = False
    await async_session.flush()

    assert (await resolve(async_session, "Siemens Energy AG")).supplier_id is None


async def test_resolve_many_preserves_order_and_marks_each(
    async_session: AsyncSession, registry
) -> None:
    results = await resolve_many(
        async_session, ["Siemens AG", "Unknown Co", "Bosch", "Siemens Energy AG"]
    )

    assert [r.surface_form for r in results] == [
        "Siemens AG",
        "Unknown Co",
        "Bosch",
        "Siemens Energy AG",
    ]
    assert [r.supplier_id is not None for r in results] == [True, False, True, True]


async def test_resolve_many_issues_one_query(
    async_session: AsyncSession, registry, monkeypatch
) -> None:
    """Enrichment resolves every name in an article; per-name round trips do not scale."""
    calls: list[int] = []
    original = AsyncSession.execute

    async def counting_execute(self, statement, *args, **kwargs):
        calls.append(1)
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", counting_execute)

    await resolve_many(
        async_session, ["Siemens AG", "Bosch", "Siemens Energy AG", "Unknown Co", "Another Ltd"]
    )

    assert len(calls) == 1


async def test_resolve_many_on_an_empty_list_touches_the_database_not_at_all(
    async_session: AsyncSession, registry, monkeypatch
) -> None:
    calls: list[int] = []
    original = AsyncSession.execute

    async def counting_execute(self, statement, *args, **kwargs):
        calls.append(1)
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", counting_execute)

    assert await resolve_many(async_session, []) == []
    assert calls == []


async def test_repeated_names_resolve_consistently(async_session: AsyncSession, registry) -> None:
    results = await resolve_many(async_session, ["Siemens", "Siemens AG", "siemens"])

    assert {r.supplier_id for r in results} == {registry["siemens"].id}
