"""End-to-end proof that a production-shaped PostgreSQL backup is restorable."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from procuresignal.models import Base, Organization
from procuresignal.operations.recovery import create_backup, restore_drill
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.postgres


async def _insert_restore_proof(url: str) -> None:
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as session:
            session.add(
                Organization(
                    public_id="org_restore_proof",
                    name="Restore Proof",
                    slug="restore-proof",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_backup_restores_current_schema_and_application_data(
    migrated_database: str, tmp_path: Path
) -> None:
    await _insert_restore_proof(migrated_database)
    archive = create_backup(migrated_database, tmp_path / "procuresignal.dump")

    receipt = await restore_drill(migrated_database, archive)

    expected_head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    assert receipt.alembic_head == expected_head
    assert set(Base.metadata.tables).issubset(receipt.tables)
    assert receipt.proof_rows == 1
