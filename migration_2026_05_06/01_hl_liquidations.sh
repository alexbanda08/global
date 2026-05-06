#!/usr/bin/env bash
# 01_hl_liquidations.sh — migrate hyperliquid_liquidations_v2 VPS2 → VPS3
# Idempotent: PK on (tid, time_exchange_us) absorbs duplicates.
# ~5M rows, ~1-2 hr.

set -euo pipefail

TABLE=hyperliquid_liquidations_v2
TMP=tmp_${TABLE}_$(date +%s)
STARTED=$(date -u +%FT%TZ)

echo "=== [$STARTED] $TABLE migration starting ==="

# 1) Pre-counts
VPS2_N=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
VPS3_N_BEFORE=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
echo "  VPS2 has $VPS2_N rows"
echo "  VPS3 has $VPS3_N_BEFORE rows BEFORE migration"
echo "  Target gap: $((VPS2_N - VPS3_N_BEFORE)) rows"

# 2) Create unlogged temp table on VPS3 with same structure
echo "  [step 1/4] Creating temp table $TMP on VPS3..."
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -v ON_ERROR_STOP=1 -c \
  "CREATE UNLOGGED TABLE $TMP (LIKE $TABLE INCLUDING DEFAULTS);"

# 3) Stream COPY VPS2 -> psql VPS3 directly
echo "  [step 2/4] Streaming rows VPS2 -> VPS3 (this is the long step)..."
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c \
  "COPY $TABLE TO STDOUT WITH (FORMAT BINARY)" \
  | PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -c \
  "COPY $TMP FROM STDIN WITH (FORMAT BINARY)"

TMP_N=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TMP;" | xargs)
echo "  Temp table received $TMP_N rows"

# 4) INSERT ... ON CONFLICT DO NOTHING
echo "  [step 3/4] Merging temp -> $TABLE with ON CONFLICT DO NOTHING..."
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -v ON_ERROR_STOP=1 -c \
  "INSERT INTO $TABLE SELECT * FROM $TMP ON CONFLICT DO NOTHING;"

# 5) Drop temp + report
echo "  [step 4/4] Dropping temp table..."
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -c \
  "DROP TABLE $TMP;"

VPS3_N_AFTER=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
INSERTED=$((VPS3_N_AFTER - VPS3_N_BEFORE))
FINISHED=$(date -u +%FT%TZ)

echo "=== [$FINISHED] $TABLE migration done ==="
echo "  rows before: $VPS3_N_BEFORE"
echo "  rows after:  $VPS3_N_AFTER"
echo "  inserted:    $INSERTED (was $TMP_N in temp; rest were duplicates)"
echo "  expected:    $((VPS2_N - VPS3_N_BEFORE)) (gap before migration)"
echo
