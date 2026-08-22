"""A real PostgreSQL database for the tests that cannot be honest on SQLite.

`tsvector`, `GIN`, `vector` and `<=>` do not exist in SQLite, so a suite that runs only
there cannot verify the search stack at all. Everything here is opt-in through
`TEST_DATABASE_URL`:

- unset locally, the Postgres tests skip and `pytest` stays fast;
- set in CI together with `REQUIRE_POSTGRES=1`, a skip becomes a failure, so the suite
  cannot go quietly green having verified nothing.

`DATABASE_URL` is deliberately *not* used as a fallback. This fixture creates and drops
databases, and a developer who has that variable exported for their dev instance should
not have a test run issuing DDL against it.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]


def _configured_url() -> str:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if url:
        return url
    if os.getenv("REQUIRE_POSTGRES") == "1":
        raise RuntimeError(
            "REQUIRE_POSTGRES=1 but TEST_DATABASE_URL is unset: the PostgreSQL suite "
            "would have skipped, which is how a database-specific regression ships."
        )
    pytest.skip("TEST_DATABASE_URL is not set", allow_module_level=True)


def _with_database(url: str, name: str) -> str:
    base, _, tail = url.rpartition("/")
    query = tail.partition("?")[2]
    return f"{base}/{name}?{query}" if query else f"{base}/{name}"


@pytest.fixture(scope="session")
def pg_url() -> str:
    return _configured_url()


@pytest.fixture(scope="session")
def migrated_database(pg_url: str) -> AsyncGenerator[str, None]:
    """One throwaway database per session, built by `alembic upgrade head`.

    Built by the migrations rather than `Base.metadata.create_all`: creating tables from
    the ORM cannot detect a migration that disagrees with the models, and that is exactly
    the defect this database exists to catch.
    """

    name = f"procuresignal_test_{uuid.uuid4().hex[:12]}"

    # A new engine per call: each asyncio.run() is a different event loop, and an asyncpg
    # connection pool created under one loop cannot be awaited from another.
    async def _admin(*statements: str) -> None:
        engine = create_async_engine(pg_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                for statement in statements:
                    await connection.exec_driver_sql(statement)
        finally:
            await engine.dispose()

    def create() -> None:
        asyncio.run(_admin(f'CREATE DATABASE "{name}"'))

    def drop() -> None:
        asyncio.run(
            _admin(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{name}' AND pid <> pg_backend_pid()",
                f'DROP DATABASE IF EXISTS "{name}"',
            )
        )

    create()
    target = _with_database(pg_url, name)

    # A subprocess, because migrations/env.py calls asyncio.run() itself and because this
    # is the command that actually runs on deploy. Testing a reimplementation of it would
    # verify the reimplementation.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": target},
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        drop()
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")

    try:
        yield target
    finally:
        drop()


@pytest.fixture
async def pg_session(migrated_database: str) -> AsyncGenerator[AsyncSession, None]:
    """A session inside a transaction that is always rolled back.

    PostgreSQL DDL is transactional, so this isolates tables a test creates as well as the
    rows it writes. `create_savepoint` lets a test call `commit()` — most of the code under
    test does — without ending the outer transaction that guarantees the rollback.
    """

    engine = create_async_engine(migrated_database)
    connection = await engine.connect()
    transaction = await connection.begin()
    maker = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        async with maker() as session:
            yield session
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
