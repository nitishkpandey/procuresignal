"""Safety and subprocess contracts for PostgreSQL recovery operations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from procuresignal.operations import recovery
from procuresignal.operations.recovery import (
    PostgresEndpoint,
    backup_command,
    create_backup,
    restore_command,
    validate_drill_database,
)
from sqlalchemy.engine import make_url

URL = "postgresql+asyncpg://buyer:p%40ss@db.example:5544/procuresignal"


def test_password_is_only_in_the_child_environment() -> None:
    endpoint = PostgresEndpoint.from_url(URL)
    command = backup_command(endpoint, Path("backup.dump"))

    assert "p@ss" not in " ".join(command)
    assert "p%40ss" not in " ".join(command)
    assert endpoint.environment({"PATH": os.environ.get("PATH", "")})["PGPASSWORD"] == "p@ss"

    target_url = endpoint.async_url("procuresignal_restore_a1b2c3d4e5f6")
    assert make_url(target_url).password == "p@ss"
    assert "p@ss" not in target_url


def test_backup_command_is_custom_format_without_ownership(tmp_path: Path) -> None:
    command = backup_command(PostgresEndpoint.from_url(URL), tmp_path / "backup.dump.tmp")

    assert command[0] == "pg_dump"
    assert "--format=custom" in command
    assert "--compress=6" in command
    assert "--no-owner" in command
    assert "--no-privileges" in command


def test_restore_command_refuses_the_source_database(tmp_path: Path) -> None:
    endpoint = PostgresEndpoint.from_url(URL)

    with pytest.raises(ValueError, match="source database"):
        restore_command(endpoint, tmp_path / "backup.dump", "procuresignal")


@pytest.mark.parametrize("name", ["postgres", "procuresignal", "restore_test", "x;drop database"])
def test_only_generated_drill_names_are_accepted(name: str) -> None:
    with pytest.raises(ValueError, match="procuresignal_restore_"):
        validate_drill_database(name, source_database="procuresignal")


def _fake_pg_dump(bin_dir: Path, body: str) -> Path:
    executable = bin_dir / "pg_dump"
    executable.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    executable.chmod(0o755)
    return executable


def _environment_with(bin_dir: Path) -> dict[str, str]:
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}


def test_existing_backup_is_not_touched_without_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "backup.dump"
    output.write_bytes(b"existing archive")

    with pytest.raises(FileExistsError):
        create_backup(URL, output)

    assert output.read_bytes() == b"existing archive"


def test_failed_backup_leaves_no_temporary_or_final_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pg_dump(
        tmp_path,
        'echo "simulated failure: $PGPASSWORD and p%40ss" >&2\nexit 7\n',
    )
    monkeypatch.setattr(os, "environ", _environment_with(tmp_path))
    output = tmp_path / "backup.dump"

    with pytest.raises(RuntimeError) as caught:
        create_backup(URL, output)

    assert not output.exists()
    assert not (tmp_path / "backup.dump.tmp").exists()
    assert "p@ss" not in str(caught.value)
    assert "p%40ss" not in str(caught.value)
    assert "simulated failure" in str(caught.value)


def test_empty_successful_backup_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pg_dump(
        tmp_path,
        'for arg in "$@"; do case "$arg" in --file=*) : > "${arg#--file=}";; esac; done\n',
    )
    monkeypatch.setattr(os, "environ", _environment_with(tmp_path))
    output = tmp_path / "backup.dump"

    with pytest.raises(RuntimeError, match="empty"):
        create_backup(URL, output)

    assert not output.exists()
    assert not (tmp_path / "backup.dump.tmp").exists()


def test_successful_backup_is_published_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pg_dump(
        tmp_path,
        'for arg in "$@"; do case "$arg" in --file=*) printf archive > "${arg#--file=}";; esac; done\n',
    )
    monkeypatch.setattr(os, "environ", _environment_with(tmp_path))
    output = tmp_path / "backup.dump"

    assert create_backup(URL, output) == output
    assert output.read_bytes() == b"archive"
    assert not (tmp_path / "backup.dump.tmp").exists()


@pytest.mark.asyncio
async def test_failed_restore_is_cleaned_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    commands: list[list[str]] = []

    monkeypatch.setattr(recovery, "_require_tool", lambda _name: None)
    monkeypatch.setattr(recovery.secrets, "token_hex", lambda _size: "a1b2c3d4e5f6")

    def fail_restore(command: list[str], **_kwargs: object) -> None:
        commands.append(command)
        if command[0] == "pg_restore":
            raise RuntimeError("pg_restore failed with exit code 1")

    monkeypatch.setattr(recovery, "_run_command", fail_restore)

    with pytest.raises(RuntimeError, match="pg_restore failed"):
        await recovery.restore_drill(URL, archive)

    assert [command[0] for command in commands] == ["createdb", "pg_restore", "dropdb"]
    assert "p@ss" not in " ".join(part for command in commands for part in command)


@pytest.mark.asyncio
async def test_keep_failed_preserves_only_a_failed_drill_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    commands: list[list[str]] = []

    monkeypatch.setattr(recovery, "_require_tool", lambda _name: None)
    monkeypatch.setattr(recovery.secrets, "token_hex", lambda _size: "a1b2c3d4e5f6")

    def fail_restore(command: list[str], **_kwargs: object) -> None:
        commands.append(command)
        if command[0] == "pg_restore":
            raise RuntimeError("restore failed")

    monkeypatch.setattr(recovery, "_run_command", fail_restore)

    with pytest.raises(RuntimeError, match="restore failed") as caught:
        await recovery.restore_drill(URL, archive, keep_failed=True)

    assert [command[0] for command in commands] == ["createdb", "pg_restore"]
    assert "procuresignal_restore_a1b2c3d4e5f6" in str(caught.value)


@pytest.mark.asyncio
async def test_successful_restore_is_verified_and_always_cleaned_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    commands: list[list[str]] = []

    monkeypatch.setattr(recovery, "_require_tool", lambda _name: None)
    monkeypatch.setattr(recovery.secrets, "token_hex", lambda _size: "a1b2c3d4e5f6")
    monkeypatch.setattr(
        recovery,
        "_run_command",
        lambda command, **_kwargs: commands.append(command),
    )

    async def verified(_url: str) -> tuple[str, frozenset[str], int]:
        return "migration-head", frozenset({"organizations"}), 1

    monkeypatch.setattr(recovery, "_verify_restored_database", verified)

    receipt = await recovery.restore_drill(URL, archive, keep_failed=True)

    assert receipt.database == "procuresignal_restore_a1b2c3d4e5f6"
    assert receipt.alembic_head == "migration-head"
    assert receipt.proof_rows == 1
    assert [command[0] for command in commands] == [
        "createdb",
        "pg_restore",
        os.sys.executable,
        "dropdb",
    ]
