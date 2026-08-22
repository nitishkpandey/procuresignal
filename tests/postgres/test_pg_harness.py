"""Proof that the PostgreSQL-backed suite actually reaches PostgreSQL.

CI has run a Postgres service since Phase 1 while every test used SQLite in-memory. That
gap let six over-length Alembic revision identifiers pass review: SQLite ignores
`VARCHAR(32)`, Postgres does not, and the migration chain was unusable on the only
database that ships. These tests exist so the harness itself is verified before anything
depends on it.
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


async def test_the_session_is_postgres_not_sqlite(pg_session: AsyncSession) -> None:
    assert pg_session.bind is not None
    assert pg_session.bind.dialect.name == "postgresql"

    version = await pg_session.scalar(text("SHOW server_version"))
    assert version is not None


async def test_pgvector_is_installed(pg_session: AsyncSession) -> None:
    """Phase 5 stores embeddings in a `vector` column, so the extension is a hard
    requirement rather than an optimisation. `postgres:15-alpine` cannot provide it."""

    installed = await pg_session.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    assert installed is not None, "the vector extension is missing: wrong Postgres image"


async def test_pgvector_computes_cosine_distance(pg_session: AsyncSession) -> None:
    """Installed is not the same as usable. The `<=>` operator is what ranking calls."""

    distance = await pg_session.scalar(
        text("SELECT '[1,0,0]'::vector <=> '[1,0,0]'::vector"),
    )
    assert distance == pytest.approx(0.0, abs=1e-6)

    orthogonal = await pg_session.scalar(
        text("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector"),
    )
    assert orthogonal == pytest.approx(1.0, abs=1e-6)


async def test_schema_comes_from_the_migrations(pg_session: AsyncSession) -> None:
    """Built by `alembic upgrade head`, not `metadata.create_all`.

    Creating tables from the ORM cannot detect a migration that disagrees with the
    models, which is the exact defect class this fixture exists to catch.
    """

    tables = await pg_session.run_sync(lambda sync: set(inspect(sync.bind).get_table_names()))

    assert "alembic_version" in tables, "schema was not built by Alembic"
    for expected in ("users", "organizations", "news_articles_raw", "watchlists", "notifications"):
        assert expected in tables


async def test_alembic_revision_identifiers_fit_the_version_column(
    pg_session: AsyncSession,
) -> None:
    """The column is `VARCHAR(32)`. A longer identifier fails only on Postgres."""

    width = await pg_session.scalar(
        text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
        )
    )
    stamped = await pg_session.scalar(text("SELECT version_num FROM alembic_version"))

    assert width == 32
    assert stamped is not None and len(stamped) <= 32


async def test_each_test_gets_an_isolated_database(pg_session: AsyncSession) -> None:
    """A shared database would make these tests order-dependent, which is how a
    Postgres suite becomes something people disable rather than fix."""

    await pg_session.execute(text("CREATE TABLE leak_check (id integer primary key)"))
    await pg_session.execute(text("INSERT INTO leak_check (id) VALUES (1)"))
    await pg_session.commit()

    assert await pg_session.scalar(text("SELECT count(*) FROM leak_check")) == 1


async def test_no_leak_from_the_previous_test(pg_session: AsyncSession) -> None:
    exists = await pg_session.scalar(text("SELECT to_regclass('public.leak_check')"))
    assert exists is None, "the previous test's table survived: databases are being reused"
