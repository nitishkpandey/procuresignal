"""One-shot: resolve supplier identity across data written before the registry.

Run after seeding suppliers, and again whenever the registry gains aliases — the
coverage figure it prints is how you tell whether the registry is worth trusting yet.

    python scripts/backfill_supplier_identity.py [--batch-size 500]

Safe to re-run: existing mentions are left alone, and ones that could not be resolved
before are retried against the current registry.
"""

import argparse
import asyncio
import os
import sys

from procuresignal.config.database import DatabaseConfig
from procuresignal.suppliers.backfill import DEFAULT_BATCH_SIZE, backfill_supplier_identity


async def run(batch_size: int) -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("[backfill] DATABASE_URL is not set", file=sys.stderr)
        return 1

    config = DatabaseConfig(database_url)
    await config.initialize()
    assert config.session_maker is not None

    try:
        async with config.session_maker() as session:
            summary = await backfill_supplier_identity(session, batch_size=batch_size)
    finally:
        await config.close()

    print(f"[backfill] articles scanned      : {summary.articles_scanned}")
    print(f"[backfill] mentions created      : {summary.mentions_created}")
    print(f"[backfill] mentions resolved     : {summary.mentions_resolved}")
    print(f"[backfill] mentions unresolved   : {summary.mentions_unresolved}")
    print(f"[backfill] registry coverage     : {summary.coverage:.1%}")
    print(f"[backfill] preferences updated   : {summary.preferences_updated}")
    print(f"[backfill] risk events updated   : {summary.risk_events_updated}")

    if summary.mentions_unresolved:
        print(
            f"[backfill] {summary.mentions_unresolved} supplier names could not be placed. "
            "GET /api/suppliers/unresolved lists them most-frequent first."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    arguments = parser.parse_args()

    return asyncio.run(run(arguments.batch_size))


if __name__ == "__main__":
    raise SystemExit(main())
