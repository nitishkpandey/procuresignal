"""Create a PostgreSQL backup or prove that an archive can be restored."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Sequence

from procuresignal.operations.recovery import create_backup, restore_drill


def _database_url(argument: str | None) -> str:
    value = argument or os.getenv("DATABASE_URL", "")
    if value is None or not value.strip():
        raise ValueError("provide --database-url or set DATABASE_URL")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup", help="create a logical backup archive")
    backup.add_argument("--database-url")
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--overwrite", action="store_true")

    drill = subparsers.add_parser("drill", help="restore and verify a backup archive")
    drill.add_argument("--database-url")
    drill.add_argument("--archive", type=Path, required=True)
    drill.add_argument("--keep-failed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        url = _database_url(args.database_url)
        if args.command == "backup":
            print(create_backup(url, args.output, overwrite=args.overwrite))
            return 0

        receipt = asyncio.run(restore_drill(url, args.archive, keep_failed=args.keep_failed))
        print(
            json.dumps(
                {
                    "database": receipt.database,
                    "alembic_head": receipt.alembic_head,
                    "tables": sorted(receipt.tables),
                    "proof_rows": receipt.proof_rows,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"database recovery failed: {exc}") from None


if __name__ == "__main__":
    raise SystemExit(main())
