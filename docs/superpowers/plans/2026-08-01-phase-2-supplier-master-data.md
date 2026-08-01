# Phase 2: Supplier Master Data and Entity Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every supplier a canonical identity, so watchlists, ranking, and sanctions
screening stop depending on whether an article happened to write "Siemens" or "Siemens AG".

**Architecture:** A `suppliers` registry holds canonical entities. Every name a supplier can be
written as — including its own — lives in `supplier_aliases`, whose normalized form is unique
across the whole table, so an ambiguous alias fails at registration rather than silently
mis-resolving later. Resolution is one indexed lookup. Article mentions become rows in a link
table, and preferences store resolved ids alongside the text the user typed.

**Tech Stack:** Python 3.11, SQLAlchemy async, Alembic, FastAPI, Pytest.

## Global Constraints

- Resolution is exact-match on normalized aliases only. No fuzzy or edit-distance matching:
  the false positives it reintroduces are the defect this phase exists to remove.
- An unresolvable mention is recorded with `supplier_id = NULL` and its surface form. It is
  never dropped and never guessed at.
- Distinct legal entities stay distinct. `Siemens AG` and `Siemens Energy AG` are two suppliers,
  because they carry different risk.
- `supplier_aliases.normalized_alias` is globally unique. Two suppliers claiming one alias is a
  database error an operator resolves, not a silent wrong answer.
- Existing JSON columns (`detected_suppliers`, `preferred_suppliers`, `excluded_suppliers`,
  `affected_suppliers`) keep working and keep their current contents. This phase adds resolved
  ids beside them; it does not remove the text.
- Every REST response contract stays backward compatible. Supplier fields may gain entries but
  must not change type.
- Admin-only supplier mutations require `Role.ADMIN` via `require_role`.
- Backend gate for every task: `PYTHONPATH="$PWD/shared:$PWD" pytest tests/ -q --no-cov`,
  `black --check .`, `ruff check .`, `mypy api worker shared`.
- Commit messages describe intent in plain language. No AI attribution trailers.

## The Defect Being Fixed

Verified against `main` before writing this plan:

```
article says 'Siemens AG'   user watches 'Siemens'            -> MISSED
article says 'BASF SE'      user watches 'BASF'               -> MISSED
article says 'Bosch'        user watches 'Robert Bosch GmbH'  -> MISSED

watching 'ABB'    vs "Local cabbage prices rose..."      -> MATCH (false positive)
watching '3M'     vs "...the 3m-long delay in shipping"  -> MATCH (false positive)
watching 'Aptiv'  vs "Captive insurance costs..."        -> MATCH (false positive)
```

Two separate causes:

| Cause | Location |
|---|---|
| Set intersection over raw strings, so any spelling difference misses | `shared/procuresignal/personalization/matcher.py:275` (`calculate_supplier_match`) |
| Substring containment against article text, so short names match inside unrelated words | `shared/procuresignal/personalization/matcher.py:97` (`_supplier_text_matches`) |

The same free-text path feeds sanctions screening, where a miss is a compliance failure rather
than a poor feed.

## File Structure

- `shared/procuresignal/models/suppliers.py`: `Supplier`, `SupplierAlias`, `ArticleSupplierMention`.
- `shared/procuresignal/suppliers/normalization.py`: pure normalization and legal-form handling.
- `shared/procuresignal/suppliers/resolver.py`: surface form to canonical id.
- `shared/procuresignal/suppliers/registry.py`: create, alias, merge, and seed operations.
- `shared/procuresignal/suppliers/seed.py`: the starting catalogue and its derived aliases.
- `api/routers/suppliers.py`: admin registry endpoints.
- `api/schemas/supplier.py`: supplier request/response contracts.
- `migrations/versions/h2i3j4_add_supplier_registry.py`: schema plus backfill.

---

### Task 1: Supplier Registry Schema

**Files:**
- Create: `shared/procuresignal/models/suppliers.py`
- Modify: `shared/procuresignal/models/__init__.py`
- Modify: `shared/procuresignal/models/preferences.py`
- Create: `migrations/versions/h2i3j4_add_supplier_registry.py`
  (`revision = "h2i3j4_add_supplier_registry"`, `down_revision = "g1h2i3_add_auth_tenancy_audit"` — the current head)
- Test: `tests/unit/test_supplier_models.py`
- Test: `tests/integration/test_supplier_migration.py`

**Interfaces:**
- Produces: `Supplier` (`public_id: str`, `canonical_name: str`, `normalized_name: str`,
  `country: str | None`, `lei: str | None`, `is_active: bool`),
  `SupplierAlias` (`supplier_id: int`, `alias: str`, `normalized_alias: str`, `source: str`),
  `ArticleSupplierMention` (`processed_article_id: int`, `supplier_id: int | None`,
  `surface_form: str`, `confidence: float`).
- Produces: `UserNewsPreference.preferred_supplier_ids: list`,
  `UserNewsPreference.excluded_supplier_ids: list` (JSON lists of supplier `public_id`).

**Design notes:**

`normalized_name` keeps the legal form (`siemens ag`), so two entities that differ only by legal
form stay distinct rows. The stripped variant (`siemens`) is written into `supplier_aliases`
instead. That is what makes the alias table the single resolution path and makes ambiguity a
constraint violation at registration time.

`ArticleSupplierMention.supplier_id` is nullable on purpose. An unresolved mention is evidence
worth keeping — it is what tells an operator which alias to add next.

The preference columns are additive. `preferred_suppliers` keeps the text the user typed, because
the UI shows it back to them and because a supplier can be added to the registry later and the
preference re-resolved.

- [ ] **Step 1: Write the failing model test**

```python
# tests/unit/test_supplier_models.py
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from procuresignal.models import ArticleSupplierMention, Base, Supplier, SupplierAlias


@pytest.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


async def test_two_suppliers_cannot_claim_one_alias(async_session: AsyncSession) -> None:
    """Ambiguity must fail loudly at registration, not resolve to an arbitrary winner."""
    first = Supplier(public_id="s1", canonical_name="Apple Inc", normalized_name="apple inc")
    second = Supplier(public_id="s2", canonical_name="Apple Bank", normalized_name="apple bank")
    async_session.add_all([first, second])
    await async_session.flush()

    async_session.add(
        SupplierAlias(supplier_id=first.id, alias="Apple", normalized_alias="apple", source="derived")
    )
    await async_session.flush()

    async_session.add(
        SupplierAlias(supplier_id=second.id, alias="Apple", normalized_alias="apple", source="derived")
    )
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_entities_differing_only_by_legal_form_stay_distinct(
    async_session: AsyncSession,
) -> None:
    """Siemens AG and Siemens Energy AG carry different risk and must not merge."""
    async_session.add_all(
        [
            Supplier(public_id="s1", canonical_name="Siemens AG", normalized_name="siemens ag"),
            Supplier(
                public_id="s2",
                canonical_name="Siemens Energy AG",
                normalized_name="siemens energy ag",
            ),
        ]
    )
    await async_session.flush()


async def test_unresolved_mentions_are_recorded_rather_than_dropped(
    async_session: AsyncSession,
) -> None:
    mention = ArticleSupplierMention(
        processed_article_id=1,
        supplier_id=None,
        surface_form="Unbekannte Lieferant GmbH",
        confidence=0.0,
    )
    async_session.add(mention)
    await async_session.flush()

    assert mention.supplier_id is None
    assert mention.surface_form == "Unbekannte Lieferant GmbH"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH="$PWD/shared:$PWD" pytest tests/unit/test_supplier_models.py -q --no-cov`
Expected: FAIL with `ImportError: cannot import name 'Supplier'`

- [ ] **Step 3: Write the models**

```python
# shared/procuresignal/models/suppliers.py
"""Supplier master data."""

from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class Supplier(BaseModel):
    """One canonical legal entity."""

    __tablename__ = "suppliers"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Keeps the legal form, so "Siemens AG" and "Siemens Energy AG" are separate rows.
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    lei: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (Index("idx_suppliers_normalized", "normalized_name"),)


class SupplierAlias(BaseModel):
    """Every spelling that resolves to a supplier, including its own canonical form.

    `normalized_alias` is unique across the table. Two suppliers claiming one alias is
    an operator decision, so it surfaces as a constraint violation rather than a silent
    arbitrary winner.
    """

    __tablename__ = "supplier_aliases"

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    # "canonical", "derived" (legal-form variant), "manual", or "lei".
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)

    __table_args__ = (
        Index("idx_alias_normalized", "normalized_alias"),
        Index("idx_alias_supplier", "supplier_id"),
    )


class ArticleSupplierMention(BaseModel):
    """A supplier named by an article.

    `supplier_id` is null when the name did not resolve. The mention is still stored:
    it is the evidence that tells an operator which alias is missing.
    """

    __tablename__ = "article_supplier_mentions"

    processed_article_id: Mapped[int] = mapped_column(nullable=False)
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    surface_form: Mapped[str] = mapped_column(String(300), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "processed_article_id", "surface_form", name="uq_mention_article_surface"
        ),
        Index("idx_mention_supplier", "supplier_id"),
        Index("idx_mention_article", "processed_article_id"),
    )
```

Add to `shared/procuresignal/models/preferences.py`, inside `UserNewsPreference`:

```python
    # Resolved at save time. The text columns above keep what the user typed, so a
    # preference can be re-resolved after the registry gains an alias.
    preferred_supplier_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded_supplier_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
```

Export `Supplier`, `SupplierAlias`, `ArticleSupplierMention` from
`shared/procuresignal/models/__init__.py`.

- [ ] **Step 4: Run to verify the tests pass**

- [ ] **Step 5: Write the migration test**

```python
# tests/integration/test_supplier_migration.py
import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_preferences_gain_empty_id_columns(monkeypatch) -> None:
    """Existing preference rows must survive with empty resolved-id lists."""
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    preferences = sa.Table(
        "user_news_preferences",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("preferred_suppliers", sa.JSON, nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            preferences.insert(), {"id": 1, "user_id": "u1", "preferred_suppliers": ["Bosch"]}
        )
        migration = importlib.import_module("migrations.versions.h2i3j4_add_supplier_registry")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()

        row = connection.execute(
            sa.text("SELECT preferred_suppliers, preferred_supplier_ids FROM user_news_preferences")
        ).one()
        assert row.preferred_suppliers == ["Bosch"] or row.preferred_suppliers == '["Bosch"]'
        assert row.preferred_supplier_ids in ([], "[]")
```

- [ ] **Step 6: Write the migration**

Create the three tables with their indexes and constraints, then add the two JSON columns to
`user_news_preferences` with `server_default='[]'` so existing rows are valid immediately.
`downgrade()` drops the three tables and the two columns; it is fully reversible because nothing
existing is rewritten.

- [ ] **Step 7: Run the full gate and commit**

```bash
git commit -m "Add supplier registry, aliases, and article mentions"
```

---

### Task 2: Normalization And Legal Forms

**Files:**
- Create: `shared/procuresignal/suppliers/__init__.py`
- Create: `shared/procuresignal/suppliers/normalization.py`
- Test: `tests/unit/test_supplier_normalization.py`

**Interfaces:**
- Produces: `normalize(name: str) -> str`, `strip_legal_form(normalized: str) -> str`,
  `alias_forms(canonical_name: str) -> list[str]`, `LEGAL_FORMS: frozenset[str]`.

**Design notes:**

`normalize` lowercases, replaces punctuation with spaces, and collapses whitespace. It does
**not** strip legal forms, because it produces `Supplier.normalized_name` where the legal form is
the thing keeping entities apart.

`strip_legal_form` removes one trailing legal form only. Stripping repeatedly would turn
"Company Co" into nothing useful, and stripping from the middle would corrupt names like
"AG Barr".

`alias_forms` returns the normalized canonical form plus the stripped form when it differs and is
long enough to be meaningful. Names of one or two characters after stripping are dropped: an
alias of "3" or "ab" matches far too much.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_supplier_normalization.py
import pytest

from procuresignal.suppliers.normalization import alias_forms, normalize, strip_legal_form


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Siemens AG", "siemens ag"),
        ("  SIEMENS   AG  ", "siemens ag"),
        ("Robert Bosch GmbH", "robert bosch gmbh"),
        ("O'Reilly Automotive, Inc.", "o reilly automotive inc"),
        ("Saint-Gobain S.A.", "saint gobain s a"),
    ],
)
def test_normalize_is_stable_across_spacing_and_punctuation(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_normalize_keeps_the_legal_form() -> None:
    """It produces the canonical key, where the legal form is what keeps entities apart."""
    assert normalize("Siemens AG") != normalize("Siemens Energy AG")
    assert "ag" in normalize("Siemens AG").split()


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        ("siemens ag", "siemens"),
        ("robert bosch gmbh", "robert bosch"),
        ("basf se", "basf"),
        ("apple inc", "apple"),
        ("nexans", "nexans"),
    ],
)
def test_strip_legal_form_removes_one_trailing_form(normalized: str, expected: str) -> None:
    assert strip_legal_form(normalized) == expected


def test_strip_legal_form_leaves_leading_matches_alone() -> None:
    """"AG Barr" is a company name, not a legal form followed by a word."""
    assert strip_legal_form("ag barr") == "ag barr"


def test_alias_forms_include_canonical_and_stripped() -> None:
    assert alias_forms("Siemens AG") == ["siemens ag", "siemens"]


def test_alias_forms_deduplicate_when_there_is_no_legal_form() -> None:
    assert alias_forms("Nexans") == ["nexans"]


@pytest.mark.parametrize("name", ["3M Co", "AB Ltd"])
def test_alias_forms_drop_dangerously_short_stripped_names(name: str) -> None:
    """A two-character alias matches half the corpus."""
    forms = alias_forms(name)
    assert all(len(form) > 2 for form in forms)
```

- [ ] **Step 2: Run to verify failure, then implement**

```python
# shared/procuresignal/suppliers/normalization.py
"""Name normalization for supplier resolution."""

import re

# Trailing legal forms, normalized. Only stripped from the end of a name.
LEGAL_FORMS = frozenset(
    {
        "ag", "gmbh", "se", "kg", "kgaa", "mbh", "ohg",
        "inc", "corp", "corporation", "co", "company", "llc", "lp", "llp",
        "ltd", "limited", "plc",
        "sa", "sas", "sarl", "sca",
        "nv", "bv", "cv",
        "spa", "srl",
        "ab", "as", "asa", "oy", "oyj", "aps",
        "pty", "pte",
        "group", "holding", "holdings",
    }
)

# Shorter than this after stripping and the alias matches far too much text.
MINIMUM_ALIAS_LENGTH = 3

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(name: str) -> str:
    """Lower-case, replace punctuation with spaces, collapse whitespace.

    Deliberately keeps the legal form: this produces `Supplier.normalized_name`, and the
    legal form is what distinguishes one entity from another.
    """

    return _NON_WORD.sub(" ", (name or "").lower()).strip()


def strip_legal_form(normalized: str) -> str:
    """Remove one trailing legal form.

    Only trailing, and only one. "AG Barr" is a company, not a legal form plus a word,
    and repeated stripping would eat "Company Co" entirely.
    """

    parts = normalized.split()
    if len(parts) > 1 and parts[-1] in LEGAL_FORMS:
        return " ".join(parts[:-1])
    return normalized


def alias_forms(canonical_name: str) -> list[str]:
    """Normalized spellings that should resolve to this supplier."""

    canonical = normalize(canonical_name)
    forms = [canonical]

    stripped = strip_legal_form(canonical)
    if stripped != canonical and len(stripped) >= MINIMUM_ALIAS_LENGTH:
        forms.append(stripped)

    return [form for form in forms if len(form) >= MINIMUM_ALIAS_LENGTH]
```

- [ ] **Step 3: Run the full gate and commit**

```bash
git commit -m "Normalize supplier names without collapsing distinct entities"
```

---

### Task 3: Resolver And Registry Operations

**Files:**
- Create: `shared/procuresignal/suppliers/resolver.py`
- Create: `shared/procuresignal/suppliers/registry.py`
- Create: `shared/procuresignal/suppliers/seed.py`
- Test: `tests/unit/test_supplier_resolver.py`
- Test: `tests/unit/test_supplier_registry.py`

**Interfaces:**
- Consumes: `normalize`, `alias_forms` (Task 2); `Supplier`, `SupplierAlias` (Task 1).
- Produces: `Resolution` frozen dataclass (`supplier_id: int | None`, `public_id: str | None`,
  `surface_form: str`, `confidence: float`);
  `resolve(session, surface_form) -> Resolution`;
  `resolve_many(session, surface_forms) -> list[Resolution]`;
  `register_supplier(session, *, canonical_name, country=None, lei=None) -> Supplier`;
  `add_alias(session, *, supplier_id, alias, source="manual") -> SupplierAlias`;
  `merge_suppliers(session, *, keep_id, merge_id) -> None`;
  `seed_suppliers(session) -> int`.

**Design notes:**

The `async_session` fixture used across these tests follows the in-memory SQLite pattern
already in `tests/unit/test_auth_models.py`. Put the shared version in `tests/conftest.py`
rather than copying it into each new file.

`resolve_many` must issue one query for the whole batch, not one per name. Enrichment resolves
every mention in an article, and a per-name round trip turns a page load into dozens of queries.

`merge_suppliers` moves aliases and mentions onto the surviving supplier, adds the merged
supplier's names as aliases, and deactivates rather than deletes the loser, so an audit trail of
what was merged survives.

`add_alias` must translate the unique-constraint violation into a domain error naming the
supplier that already holds the alias. "IntegrityError" tells an operator nothing.

Seeding starts from the 14 names already in `shared/procuresignal/enrichment/entities.py`
(`KNOWN_SUPPLIERS`). It is a starting point, not a catalogue.

- [ ] **Step 1: Write the failing resolver tests**

```python
# tests/unit/test_supplier_resolver.py
import pytest

from procuresignal.suppliers.registry import add_alias, register_supplier
from procuresignal.suppliers.resolver import resolve, resolve_many


@pytest.fixture
async def registry(async_session):
    siemens = await register_supplier(async_session, canonical_name="Siemens AG", country="DE")
    energy = await register_supplier(
        async_session, canonical_name="Siemens Energy AG", country="DE"
    )
    bosch = await register_supplier(
        async_session, canonical_name="Robert Bosch GmbH", country="DE"
    )
    await add_alias(async_session, supplier_id=bosch.id, alias="Bosch")
    await async_session.flush()
    return {"siemens": siemens, "energy": energy, "bosch": bosch}


@pytest.mark.parametrize(
    "surface", ["Siemens AG", "siemens ag", "  SIEMENS   AG ", "Siemens", "Siemens, AG."]
)
async def test_spelling_variants_resolve_to_one_entity(async_session, registry, surface) -> None:
    """This is the miss the phase exists to fix."""
    resolution = await resolve(async_session, surface)
    assert resolution.supplier_id == registry["siemens"].id
    assert resolution.confidence == 1.0


async def test_a_spinoff_does_not_resolve_to_its_parent(async_session, registry) -> None:
    """Siemens Energy carries different risk and must stay separate."""
    resolution = await resolve(async_session, "Siemens Energy AG")
    assert resolution.supplier_id == registry["energy"].id
    assert resolution.supplier_id != registry["siemens"].id


async def test_manual_alias_resolves(async_session, registry) -> None:
    assert (await resolve(async_session, "Bosch")).supplier_id == registry["bosch"].id
    assert (await resolve(async_session, "Robert Bosch GmbH")).supplier_id == registry["bosch"].id


async def test_unknown_name_is_unresolved_not_guessed(async_session, registry) -> None:
    resolution = await resolve(async_session, "Some Company Nobody Registered")

    assert resolution.supplier_id is None
    assert resolution.confidence == 0.0
    assert resolution.surface_form == "Some Company Nobody Registered"


@pytest.mark.parametrize("noise", ["cabbage", "3m-long delay", "Captive insurance"])
async def test_substrings_of_unrelated_words_do_not_resolve(async_session, registry, noise) -> None:
    """The old matcher matched 'ABB' inside 'cabbage'. Exact alias lookup cannot."""
    assert (await resolve(async_session, noise)).supplier_id is None


async def test_resolve_many_uses_a_single_query(async_session, registry) -> None:
    from sqlalchemy import event

    queries: list[str] = []
    engine = async_session.get_bind().sync_engine
    event.listen(engine, "before_cursor_execute", lambda *a: queries.append(a[2]))
    try:
        results = await resolve_many(
            async_session, ["Siemens AG", "Bosch", "Siemens Energy AG", "Unknown Co"]
        )
    finally:
        event.remove(engine, "before_cursor_execute", lambda *a: queries.append(a[2]))

    assert len([q for q in queries if "supplier_aliases" in q]) == 1
    assert [r.supplier_id is not None for r in results] == [True, True, True, False]
```

- [ ] **Step 2: Write the failing registry tests**

```python
# tests/unit/test_supplier_registry.py
import pytest

from procuresignal.suppliers.registry import (
    AmbiguousAliasError,
    add_alias,
    merge_suppliers,
    register_supplier,
)
from procuresignal.suppliers.resolver import resolve


async def test_registering_creates_canonical_and_stripped_aliases(async_session) -> None:
    supplier = await register_supplier(async_session, canonical_name="Siemens AG")
    await async_session.flush()

    assert (await resolve(async_session, "Siemens AG")).supplier_id == supplier.id
    assert (await resolve(async_session, "Siemens")).supplier_id == supplier.id


async def test_conflicting_alias_names_the_existing_holder(async_session) -> None:
    """An operator needs to know which supplier already owns the alias."""
    first = await register_supplier(async_session, canonical_name="Apple Inc")
    second = await register_supplier(async_session, canonical_name="Apple Bank")
    await async_session.flush()

    with pytest.raises(AmbiguousAliasError) as exc:
        await add_alias(async_session, supplier_id=second.id, alias="Apple")
        await async_session.flush()

    assert str(first.public_id) in str(exc.value)


async def test_merging_moves_aliases_and_keeps_the_loser_for_audit(async_session) -> None:
    keep = await register_supplier(async_session, canonical_name="Siemens AG")
    duplicate = await register_supplier(async_session, canonical_name="Siemens Aktiengesellschaft")
    await async_session.flush()

    await merge_suppliers(async_session, keep_id=keep.id, merge_id=duplicate.id)
    await async_session.flush()

    assert (await resolve(async_session, "Siemens Aktiengesellschaft")).supplier_id == keep.id
    assert duplicate.is_active is False
```

- [ ] **Step 3: Implement, verify green, run the full gate, and commit**

```bash
git commit -m "Resolve supplier names through a unique alias index"
```

---

### Task 4: Resolve Mentions During Enrichment

**Files:**
- Modify: `shared/procuresignal/enrichment/pipeline.py`
- Create: `shared/procuresignal/suppliers/mentions.py`
- Test: `tests/unit/test_supplier_mentions.py`

**Interfaces:**
- Consumes: `resolve_many` (Task 3); `ArticleSupplierMention` (Task 1).
- Produces: `record_mentions(session, *, processed_article_id, surface_forms) -> list[Resolution]`.

**Design notes:**

`detected_suppliers` keeps its current contents unchanged. Mentions are written alongside it, so
nothing downstream breaks while the rewiring in Task 5 lands.

`record_mentions` must be idempotent: enrichment can re-run over an article, and the unique
constraint on `(processed_article_id, surface_form)` makes a second pass a no-op rather than a
duplicate row or a crash.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_supplier_mentions.py
async def test_records_resolved_and_unresolved_mentions(async_session, registry) -> None:
    resolutions = await record_mentions(
        async_session, processed_article_id=1, surface_forms=["Siemens AG", "Nobody Ltd"]
    )
    await async_session.flush()

    rows = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert len(rows) == 2
    assert {r.supplier_id is None for r in rows} == {False, True}
    assert [r.confidence for r in resolutions] == [1.0, 0.0]


async def test_re_running_enrichment_does_not_duplicate_mentions(async_session, registry) -> None:
    for _ in range(3):
        await record_mentions(
            async_session, processed_article_id=1, surface_forms=["Siemens AG"]
        )
        await async_session.flush()

    rows = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert len(rows) == 1


async def test_blank_and_duplicate_surface_forms_are_ignored(async_session, registry) -> None:
    await record_mentions(
        async_session, processed_article_id=1, surface_forms=["Siemens AG", "  ", "Siemens AG", ""]
    )
    await async_session.flush()

    rows = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert len(rows) == 1
```

- [ ] **Step 2: Implement, verify green, run the full gate, and commit**

```bash
git commit -m "Record which suppliers each article names"
```

---

### Task 5: Match Preferences On Supplier Identity

**Files:**
- Modify: `shared/procuresignal/personalization/matcher.py:97` and `:275`
- Modify: `shared/procuresignal/personalization/preference_manager.py`
- Test: `tests/unit/test_supplier_matching.py`
- Test: `tests/unit/test_personalization.py` (existing, update expectations)

**This task fixes both halves of the defect.**

**Design notes:**

Preferences resolve to `preferred_supplier_ids` when saved, in `PreferenceManager`. Matching then
compares id sets, which is what makes "Siemens" find "Siemens AG".

The substring fallback in `_supplier_text_matches` becomes a word-boundary regex, matching the
approach `extract_suppliers_from_text` already uses at
`shared/procuresignal/enrichment/entities.py:158`. That single change removes the
ABB-inside-cabbage class of false positive, and it must stay even for names that never resolve,
because unregistered suppliers still fall back to text.

Unresolved preference text keeps working through the existing string path. A user watching a
supplier nobody has registered must not silently stop receiving anything.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_supplier_matching.py
import pytest

from procuresignal.personalization.matcher import PreferenceMatcher


@pytest.mark.parametrize(
    ("article_says", "user_watches"),
    [
        ("Siemens AG", "Siemens"),
        ("Siemens", "Siemens AG"),
        ("BASF SE", "BASF"),
        ("Robert Bosch GmbH", "Bosch"),
    ],
)
async def test_spelling_differences_no_longer_miss(
    async_session, registry, article_says, user_watches
) -> None:
    score = await PreferenceMatcher.supplier_match_by_id(
        async_session, article_surface_forms=[article_says], preferred_text=[user_watches]
    )
    assert score > 0.5


@pytest.mark.parametrize(
    ("watched", "text"),
    [
        ("ABB", "Local cabbage prices rose sharply."),
        ("3M", "The Q3 margin fell after the 3m-long delay."),
        ("Aptiv", "Captive insurance costs increased."),
    ],
)
def test_short_names_no_longer_match_inside_words(watched: str, text: str) -> None:
    """The exact false positives measured on main before this phase."""
    assert PreferenceMatcher.text_mentions_supplier(text, watched) is False


@pytest.mark.parametrize(
    ("watched", "text"),
    [
        ("ABB", "ABB won the substation contract."),
        ("3M", "3M raised prices."),
        ("Bosch", "Suppliers including Bosch, Continental and ZF."),
    ],
)
def test_genuine_mentions_still_match(watched: str, text: str) -> None:
    assert PreferenceMatcher.text_mentions_supplier(text, watched) is True


async def test_a_spinoff_does_not_satisfy_a_parent_watch(async_session, registry) -> None:
    score = await PreferenceMatcher.supplier_match_by_id(
        async_session, article_surface_forms=["Siemens Energy AG"], preferred_text=["Siemens AG"]
    )
    assert score <= 0.5


async def test_unregistered_supplier_still_matches_on_text(async_session) -> None:
    """A user must not silently stop receiving news for a supplier nobody registered."""
    score = await PreferenceMatcher.supplier_match_by_id(
        async_session,
        article_surface_forms=["Obscure Parts Ltd"],
        preferred_text=["Obscure Parts Ltd"],
    )
    assert score > 0.5
```

- [ ] **Step 2: Implement, verify green, run the full gate, and commit**

```bash
git commit -m "Match watched suppliers by identity instead of spelling"
```

---

### Task 6: Resolve Risk Events And Sanctions Screening

**Files:**
- Modify: `shared/procuresignal/risk_events/detector.py:139`
- Modify: `shared/procuresignal/risk_events/persistence.py`
- Modify: `shared/procuresignal/retrieval/providers/sanctions.py`
- Test: `tests/unit/test_sanctions_screening.py`
- Test: `tests/unit/test_risk_event_detector.py` (existing, update expectations)

**Design notes:**

This is the compliance-relevant half. A sanctions designation naming "Siemens Aktiengesellschaft"
must match a registered supplier "Siemens AG", or screening reports a false negative.

Designations already parsed by the sanctions adapter carry a primary name plus alias list. Each
of those becomes a resolution attempt, and a match records a screening hit against the supplier.

An unresolved designation is **not** silently discarded. It is recorded as an unresolved mention
so an operator can see what screening could not place, which is the difference between a control
that works and one that looks like it works.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_sanctions_screening.py
async def test_designation_alias_matches_a_registered_supplier(async_session, registry) -> None:
    """A miss here is a compliance failure, not a poor feed."""
    hits = await screen_designation(
        async_session,
        primary_name="Siemens Aktiengesellschaft",
        aliases=["Siemens AG", "SIEMENS"],
    )
    assert registry["siemens"].id in {hit.supplier_id for hit in hits}


async def test_unmatched_designation_is_recorded_not_dropped(async_session, registry) -> None:
    hits = await screen_designation(
        async_session, primary_name="Entirely Unknown Entity", aliases=[]
    )
    assert hits == []
    unresolved = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert any(row.supplier_id is None for row in unresolved)


async def test_screening_does_not_match_a_different_legal_entity(async_session, registry) -> None:
    hits = await screen_designation(
        async_session, primary_name="Siemens Energy AG", aliases=[]
    )
    assert registry["siemens"].id not in {hit.supplier_id for hit in hits}
```

- [ ] **Step 2: Implement, verify green, run the full gate, and commit**

```bash
git commit -m "Screen sanctions designations against canonical suppliers"
```

---

### Task 7: Backfill Existing Data

**Files:**
- Create: `scripts/backfill_supplier_mentions.py`
- Test: `tests/integration/test_supplier_backfill.py`

**Design notes:**

A one-off script rather than a migration step. Resolving every historical article inside a schema
migration would hold a transaction open across the whole table, and it needs to be re-runnable
after the registry gains aliases. Migrations should not be re-run.

The script is idempotent, processes in batches, and reports how many mentions resolved so an
operator can judge registry coverage before trusting the feed.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_supplier_backfill.py
async def test_backfill_resolves_existing_articles(session, registry) -> None:
    session.add(processed_article(detected_suppliers=["Siemens AG", "Nobody Ltd"]))
    await session.commit()

    summary = await backfill(session, batch_size=100)

    assert summary.resolved == 1
    assert summary.unresolved == 1


async def test_backfill_is_safe_to_re_run(session, registry) -> None:
    session.add(processed_article(detected_suppliers=["Siemens AG"]))
    await session.commit()

    first = await backfill(session, batch_size=100)
    second = await backfill(session, batch_size=100)

    assert first.resolved == 1
    assert second.resolved == 0  # already recorded
    rows = (await session.execute(select(ArticleSupplierMention))).scalars().all()
    assert len(rows) == 1
```

- [ ] **Step 2: Implement, verify green, run the full gate, and commit**

```bash
git commit -m "Backfill supplier mentions for existing articles"
```

---

### Task 8: Supplier Administration Endpoints

**Files:**
- Create: `api/routers/suppliers.py`
- Create: `api/schemas/supplier.py`
- Modify: `api/routers/__init__.py`, `api/main.py`
- Test: `tests/integration/test_supplier_api.py`

**Interfaces:**
- Produces: `GET /api/suppliers`, `POST /api/suppliers`, `POST /api/suppliers/{public_id}/aliases`,
  `POST /api/suppliers/{public_id}/merge`, `GET /api/suppliers/unresolved`.

**Design notes:**

Without these, a wrong or missing resolution is unfixable, and an entity-resolution system nobody
can correct gets abandoned. Reads require an authenticated user; every mutation requires
`Role.ADMIN` via `require_role`.

`GET /api/suppliers/unresolved` lists the most frequent unresolved surface forms. It is the
working queue that turns coverage from a guess into a list, and it is what makes the "record
rather than drop" decision in Tasks 4 and 6 pay off.

Every mutation writes an audit record through `record_audit`, because changing supplier identity
changes what sanctions screening matches.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_supplier_api.py
def test_creating_a_supplier_requires_admin(client, member_headers, admin_headers) -> None:
    assert client.post(
        "/api/suppliers", headers=member_headers, json={"canonical_name": "New Co"}
    ).status_code == 403
    assert client.post(
        "/api/suppliers", headers=admin_headers, json={"canonical_name": "New Co"}
    ).status_code == 201


def test_reading_suppliers_requires_only_authentication(client, member_headers) -> None:
    assert client.get("/api/suppliers").status_code == 401
    assert client.get("/api/suppliers", headers=member_headers).status_code == 200


def test_conflicting_alias_returns_409_naming_the_holder(client, admin_headers) -> None:
    client.post("/api/suppliers", headers=admin_headers, json={"canonical_name": "Apple Inc"})
    second = client.post(
        "/api/suppliers", headers=admin_headers, json={"canonical_name": "Apple Bank"}
    ).json()

    conflict = client.post(
        f"/api/suppliers/{second['public_id']}/aliases",
        headers=admin_headers,
        json={"alias": "Apple"},
    )
    assert conflict.status_code == 409
    assert "Apple Inc" in conflict.text


def test_unresolved_queue_ranks_by_frequency(client, admin_headers, seeded_mentions) -> None:
    body = client.get("/api/suppliers/unresolved", headers=admin_headers).json()
    assert body["items"][0]["surface_form"] == "Frequent Unknown Ltd"
    assert body["items"][0]["mention_count"] >= 2


def test_supplier_mutations_are_audited(client, admin_headers, audit_rows) -> None:
    client.post("/api/suppliers", headers=admin_headers, json={"canonical_name": "Audited Co"})
    assert ("supplier.create", "success") in audit_rows()
```

- [ ] **Step 2: Implement, verify green, run the full gate, commit, and push**

```bash
git commit -m "Let admins correct supplier identity"
git push origin main
```

---

## Self-Review

**Spec coverage against the roadmap's D5:**

| D5 requirement | Task |
|---|---|
| Canonical IDs | 1 |
| Alias sets | 1, 2, 3 |
| Country and LEI | 1 |
| Resolution with confidence score | 3 |
| Manual override path | 8 |
| Downstream keyed off supplier IDs | 4, 5, 6 |
| Sanctions screening no longer on free text | 6 |

**Type consistency:** `Resolution` is produced in Task 3 and consumed unchanged in Tasks 4, 5,
and 6. `Supplier.public_id` is the string used in preference id lists (Task 1), API paths
(Task 8), and error messages (Task 3). `ArticleSupplierMention.supplier_id` is nullable
everywhere it appears.

**Ordering check:** Task 5 depends on preference id columns (Task 1) and `resolve` (Task 3).
Task 6 depends on Task 3 only. Task 7 depends on Tasks 3 and 4. Task 8 depends on Task 3. No task
references anything defined later.

**Deliberately out of scope, with reasons:**

- **Fuzzy and edit-distance matching.** It reintroduces the false positives this phase removes.
  Revisit only when the unresolved queue from Task 8 shows a large tail of near-misses that
  aliases cannot cover.
- **GLEIF import.** The registry and alias source field are shaped for it (`source="lei"`), but
  a 2.5M-entity import job is its own piece of work and the value depends on how much of the
  unresolved queue it would actually close. Decide with data from Task 8.
- **Re-resolving preferences when aliases change.** Preferences resolve at save time. A newly
  added alias does not retroactively update saved preferences until the user edits them or the
  backfill script is re-run. This is a real gap; the honest fix is a background job, and it
  belongs with the scheduled work in Phase 3.
- **Supplier profile pages, watchlists, and exposure scoring.** Phase 4 and Phase 5. This phase
  builds the identity they need, and the mentions link table is the query surface they will use.
- **Multi-tier supplier relationships.** Requires supplier-to-supplier data nobody has.
