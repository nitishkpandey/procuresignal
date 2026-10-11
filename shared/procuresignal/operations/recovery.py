"""Safe PostgreSQL backup and restore-drill operations."""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, quote_plus

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import create_async_engine

from procuresignal.models import Base, Organization

SUPPORTED_DRIVERS = {"postgresql", "postgresql+asyncpg"}
DRILL_DATABASE_PATTERN = re.compile(r"^procuresignal_restore_[0-9a-f]{12}$")
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PostgresEndpoint:
    """Connection fields suitable for PostgreSQL command-line tools."""

    host: str
    port: int
    username: str
    password: str | None
    database: str

    @classmethod
    def from_url(cls, url: str) -> PostgresEndpoint:
        """Parse a PostgreSQL URL without retaining its printable form."""

        parsed = make_url(url)
        if parsed.drivername not in SUPPORTED_DRIVERS:
            raise ValueError("database URL must use PostgreSQL")
        if not parsed.host or not parsed.username or not parsed.database:
            raise ValueError("database URL must include host, username, and database")
        return cls(
            host=parsed.host,
            port=parsed.port or 5432,
            username=parsed.username,
            password=parsed.password,
            database=parsed.database,
        )

    def tool_args(self, database: str | None = None) -> list[str]:
        """Return PostgreSQL client arguments that never contain credentials."""

        return [
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--username",
            self.username,
            "--dbname",
            database or self.database,
        ]

    def environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return a child environment with the password outside command arguments."""

        environment = dict(os.environ if base is None else base)
        if self.password is not None:
            environment["PGPASSWORD"] = self.password
        else:
            environment.pop("PGPASSWORD", None)
        return environment

    def async_url(self, database: str) -> str:
        """Build a correctly escaped async SQLAlchemy URL for a target database."""

        validate_drill_database(database, source_database=self.database)
        return URL.create(
            "postgresql+asyncpg",
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=database,
        ).render_as_string(hide_password=False)


@dataclass(frozen=True)
class RestoreReceipt:
    """Non-secret evidence produced by a successful restore drill."""

    database: str
    alembic_head: str
    tables: frozenset[str]
    proof_rows: int


def validate_drill_database(name: str, *, source_database: str) -> None:
    """Reject every restore target except a generated isolated drill database."""

    if name == source_database:
        raise ValueError(
            "restore database cannot be the source database; target must match "
            "procuresignal_restore_<12 lowercase hex>"
        )
    if not DRILL_DATABASE_PATTERN.fullmatch(name):
        raise ValueError("restore database must match procuresignal_restore_<12 lowercase hex>")


def backup_command(endpoint: PostgresEndpoint, temporary_output: Path) -> list[str]:
    """Build the pg_dump command for a portable logical archive."""

    return [
        "pg_dump",
        *endpoint.tool_args(),
        "--format=custom",
        "--compress=6",
        "--no-owner",
        "--no-privileges",
        f"--file={temporary_output}",
    ]


def restore_command(endpoint: PostgresEndpoint, archive: Path, database: str) -> list[str]:
    """Build a fail-fast pg_restore command for an isolated drill database."""

    validate_drill_database(database, source_database=endpoint.database)
    return [
        "pg_restore",
        *endpoint.tool_args(database),
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        str(archive),
    ]


def _administrative_args(endpoint: PostgresEndpoint) -> list[str]:
    return [
        "--host",
        endpoint.host,
        "--port",
        str(endpoint.port),
        "--username",
        endpoint.username,
        "--maintenance-db",
        endpoint.database,
    ]


def _create_database_command(endpoint: PostgresEndpoint, database: str) -> list[str]:
    validate_drill_database(database, source_database=endpoint.database)
    return ["createdb", *_administrative_args(endpoint), database]


def _drop_database_command(endpoint: PostgresEndpoint, database: str) -> list[str]:
    validate_drill_database(database, source_database=endpoint.database)
    return ["dropdb", *_administrative_args(endpoint), "--if-exists", "--force", database]


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"required PostgreSQL client tool is unavailable: {name}")


def _run_command(command: list[str], *, environment: Mapping[str, str], operation: str) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            env=dict(environment),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{operation} timed out") from None
    except subprocess.CalledProcessError as exc:
        detail = _sanitized_diagnostic(exc.stderr, environment=environment)
        raise RuntimeError(
            f"{operation} failed with exit code {exc.returncode}: {detail}"
        ) from None


def _sanitized_diagnostic(detail: str | None, *, environment: Mapping[str, str]) -> str:
    """Keep bounded child diagnostics while removing every known credential form."""

    sanitized = (detail or "").strip()
    password = environment.get("PGPASSWORD", "")
    secrets_to_remove = {
        password,
        quote(password, safe="") if password else "",
        quote_plus(password) if password else "",
        environment.get("DATABASE_URL", ""),
    }
    for secret in sorted((value for value in secrets_to_remove if value), key=len, reverse=True):
        sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized[-2000:] or "no child diagnostic was returned"


def create_backup(url: str, output: Path, *, overwrite: bool = False) -> Path:
    """Create a non-empty custom-format archive and publish it atomically."""

    output = output.expanduser().resolve()
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    if output.exists() and not overwrite:
        raise FileExistsError(f"backup output already exists: {output}")
    if temporary_output.exists():
        raise FileExistsError(f"temporary backup output already exists: {temporary_output}")

    _require_tool("pg_dump")
    endpoint = PostgresEndpoint.from_url(url)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        _run_command(
            backup_command(endpoint, temporary_output),
            environment=endpoint.environment(),
            operation="pg_dump",
        )
        if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty backup archive")
        if output.exists() and not overwrite:
            raise FileExistsError(f"backup output appeared while pg_dump was running: {output}")
        temporary_output.replace(output)
    finally:
        temporary_output.unlink(missing_ok=True)

    return output


def _current_alembic_head() -> str:
    head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no current head")
    return head


async def _verify_restored_database(database_url: str) -> tuple[str, frozenset[str], int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            alembic_head = str(
                (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one()
            )
            tables = frozenset(
                await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_table_names()
                )
            )
            proof_rows = int(
                (
                    await connection.execute(
                        select(text("count(*)"))
                        .select_from(Organization)
                        .where(Organization.slug == "restore-proof")
                    )
                ).scalar_one()
            )
    finally:
        await engine.dispose()

    expected_head = _current_alembic_head()
    if alembic_head != expected_head:
        raise RuntimeError("restored database is not at the current Alembic head")
    missing_tables = set(Base.metadata.tables) - tables
    if missing_tables:
        raise RuntimeError(f"restored database is missing {len(missing_tables)} declared table(s)")
    return alembic_head, tables, proof_rows


async def restore_drill(url: str, archive: Path, *, keep_failed: bool = False) -> RestoreReceipt:
    """Restore an archive into an isolated database and verify application readiness."""

    archive = archive.expanduser().resolve()
    if not archive.is_file() or archive.stat().st_size == 0:
        raise ValueError("restore archive must be an existing non-empty file")

    for tool in ("createdb", "pg_restore", "dropdb"):
        _require_tool(tool)

    endpoint = PostgresEndpoint.from_url(url)
    database = f"procuresignal_restore_{secrets.token_hex(6)}"
    environment = endpoint.environment()
    target_url = endpoint.async_url(database)
    created = False
    failed = True

    try:
        await asyncio.to_thread(
            _run_command,
            _create_database_command(endpoint, database),
            environment=environment,
            operation="createdb",
        )
        created = True
        await asyncio.to_thread(
            _run_command,
            restore_command(endpoint, archive, database),
            environment=environment,
            operation="pg_restore",
        )
        migration_environment = {**environment, "DATABASE_URL": target_url}
        await asyncio.to_thread(
            _run_command,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            environment=migration_environment,
            operation="alembic upgrade",
        )
        alembic_head, tables, proof_rows = await _verify_restored_database(target_url)
        failed = False
        return RestoreReceipt(
            database=database,
            alembic_head=alembic_head,
            tables=tables,
            proof_rows=proof_rows,
        )
    except Exception as exc:
        if created and keep_failed:
            raise RuntimeError(
                f"restore drill database {database} preserved after failure: {exc}"
            ) from None
        raise
    finally:
        if created and not (failed and keep_failed):
            await asyncio.to_thread(
                _run_command,
                _drop_database_command(endpoint, database),
                environment=environment,
                operation="dropdb",
            )
