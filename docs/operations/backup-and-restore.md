# Backup And Restore Runbook

ProcureSignal uses PostgreSQL custom-format logical archives. A backup is not accepted as
recoverable until the restore drill has recreated it in an isolated database and verified
the current migration head, every ORM-declared table, and a live query.

## Create a backup

Run from the repository root with PostgreSQL client tools installed:

```bash
poetry run python scripts/database_recovery.py backup \
  --output /secure/backups/procuresignal-$(date +%Y%m%dT%H%M%S).dump
```

The command reads `DATABASE_URL`, or accepts `--database-url`. The password is passed only
through the child process environment and is never placed in command arguments or receipts.
The archive is written to a sibling `.tmp` path, checked for non-zero size, and atomically
published. Existing output is rejected. Use `--overwrite` only as an explicit operator
decision; routine jobs should always choose a new timestamped path.

## Prove an archive can be restored

```bash
poetry run python scripts/database_recovery.py drill \
  --archive /secure/backups/procuresignal-20261011T010000.dump
```

The drill creates a generated `procuresignal_restore_<12-hex>` database on the same server,
runs `pg_restore`, applies `alembic upgrade head`, verifies schema and application readiness,
prints a non-secret JSON receipt, and removes the drill database. It never restores into the
source database. A failed drill is also removed by default; `--keep-failed` preserves only a
failed drill database for diagnosis and makes the operator responsible for deleting it.

To confirm cleanup manually:

```sql
SELECT datname
FROM pg_database
WHERE datname LIKE 'procuresignal_restore_%';
```

No rows should remain outside an active drill or an explicitly preserved failure.

## Failure handling

- A missing client tool, failed child command, empty archive, migration mismatch, missing
  table, or failed readiness query makes the command exit non-zero.
- A failed backup removes its temporary file and never publishes a partial final archive.
- Exceptions include at most the final 2,000 characters of child diagnostics after removing
  the database URL and raw or encoded password. Full diagnostics remain in database/server
  logs; never paste a connection URL into an incident ticket.
- If cleanup fails, treat the generated database name in the error context as operational
  residue and remove it with `dropdb --force` after confirming it matches the drill pattern.

## Scheduling, storage, and recovery objectives

Until the production host is selected, the repository deliberately does not pretend to
configure off-host storage or a production schedule. The deployment owner must provide:

1. an automated backup schedule based on the accepted recovery-point objective (RPO);
2. encrypted, access-controlled, off-host storage with retention and deletion policies;
3. periodic restore drills in an isolated environment;
4. alerts for backup or drill failures; and
5. measured recovery time from drill start to a successful receipt (the observed RTO).

Start with daily backups and a monthly restore drill only as a planning baseline. Final RPO,
RTO, replication region, encryption-key ownership, and retention must be agreed with the
business and implemented on the selected hosting platform. A copied archive without a recent
successful restore receipt is not evidence of recoverability.

The shipped API image is based on Debian Bookworm so its PostgreSQL 15 client matches the
PostgreSQL 15 server used by Compose and CI. Keep those major versions aligned when upgrading;
a dump produced by a newer client can contain settings an older server cannot restore.
