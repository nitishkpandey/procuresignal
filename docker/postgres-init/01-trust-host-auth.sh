#!/bin/sh
set -eu

PG_HBA="$PGDATA/pg_hba.conf"

if [ -f "$PG_HBA" ]; then
  TMP_FILE="$(mktemp)"
  {
    printf '%s\n' 'hostssl all all all trust'
    printf '%s\n' 'hostnossl all all all trust'
    printf '%s\n' 'host all all all trust'
    cat "$PG_HBA"
  } > "$TMP_FILE"
  cat "$TMP_FILE" > "$PG_HBA"
  rm -f "$TMP_FILE"
fi
