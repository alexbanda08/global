#!/usr/bin/env bash
# 03_markets.sh — migrate markets VPS2 → VPS3 (older 756 rows)
# Idempotent: PK on (market_id) absorbs duplicates.
# Tiny — ~1 min.

set -euo pipefail

TABLE=markets
TMP=tmp_${TABLE}_$(date +%s)
STARTED=$(date -u +%FT%TZ)

echo "=== [$STARTED] $TABLE migration starting ==="

VPS2_N=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
VPS3_N_BEFORE=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
echo "  VPS2 has $VPS2_N rows"
echo "  VPS3 has $VPS3_N_BEFORE rows BEFORE migration"

echo "  [step 1/4] Creating temp table $TMP on VPS3..."
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -v ON_ERROR_STOP=1 -c \
  "CREATE UNLOGGED TABLE $TMP (LIKE $TABLE INCLUDING DEFAULTS);"

echo "  [step 2/4] Streaming rows..."
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c \
  "COPY $TABLE TO STDOUT WITH (FORMAT BINARY)" \
  | PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -c \
  "COPY $TMP FROM STDIN WITH (FORMAT BINARY)"

TMP_N=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TMP;" | xargs)
echo "  Temp received $TMP_N rows"

echo "  [step 3/4] Merging with ON CONFLICT (market_id) DO NOTHING..."
# markets PK is (market_id), so explicit conflict target is fine. NOTE: VPS3 may
# have evolving fields like volume / yes_bid / etc. We deliberately DO NOTHING
# (don't overwrite VPS3's fresher snapshot of fields like volume_24h/last_price).
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -v ON_ERROR_STOP=1 -c \
  "INSERT INTO $TABLE SELECT * FROM $TMP ON CONFLICT (market_id) DO NOTHING;"

echo "  [step 4/4] Dropping temp..."
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -c \
  "DROP TABLE $TMP;"

VPS3_N_AFTER=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
INSERTED=$((VPS3_N_AFTER - VPS3_N_BEFORE))
FINISHED=$(date -u +%FT%TZ)

echo "=== [$FINISHED] $TABLE migration done ==="
echo "  rows before: $VPS3_N_BEFORE"
echo "  rows after:  $VPS3_N_AFTER"
echo "  inserted:    $INSERTED"
echo
