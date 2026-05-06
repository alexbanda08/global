#!/usr/bin/env bash
# 05_orderbook_snapshots.sh — migrate orderbook_snapshots_v2 VPS2 → VPS3
# 35M rows total VPS2; ~1.5M missing on VPS3 (mix of historical gap + daily 7-10% live loss).
# Largest table. ~2-3 hr.

set -euo pipefail

TABLE=orderbook_snapshots_v2
TMP=tmp_${TABLE}_$(date +%s)
STARTED=$(date -u +%FT%TZ)

echo "=== [$STARTED] $TABLE migration starting ==="

VPS2_N=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
VPS3_N_BEFORE=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TABLE;" | xargs)
echo "  VPS2 has $VPS2_N rows"
echo "  VPS3 has $VPS3_N_BEFORE rows BEFORE migration"
echo "  Expected gap: $((VPS2_N - VPS3_N_BEFORE)) rows"

echo "  [step 1/4] Creating temp table $TMP on VPS3..."
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -v ON_ERROR_STOP=1 -c \
  "CREATE UNLOGGED TABLE $TMP (LIKE $TABLE INCLUDING DEFAULTS);"

echo "  [step 2/4] Streaming ~35M rows VPS2 -> VPS3 (longest step; expect 1-2hr)..."
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c \
  "COPY $TABLE TO STDOUT WITH (FORMAT BINARY)" \
  | PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -c \
  "COPY $TMP FROM STDIN WITH (FORMAT BINARY)"

TMP_N=$(PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -t -c \
  "SELECT COUNT(*) FROM $TMP;" | xargs)
echo "  Temp received $TMP_N rows"

echo "  [step 3/4] Merging in 2-day chunks..."
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -v ON_ERROR_STOP=1 <<SQL
DO \$\$
DECLARE
    min_ts BIGINT;
    max_ts BIGINT;
    chunk_us BIGINT := 86400000000 * 2;  -- 2-day window
    cur_ts BIGINT;
    inserted_total BIGINT := 0;
    chunk_inserted BIGINT;
BEGIN
    SELECT MIN(timestamp_us), MAX(timestamp_us) INTO min_ts, max_ts FROM $TMP;
    cur_ts := min_ts;
    WHILE cur_ts <= max_ts LOOP
        WITH ins AS (
            INSERT INTO $TABLE
            SELECT * FROM $TMP
            WHERE timestamp_us >= cur_ts AND timestamp_us < cur_ts + chunk_us
            ON CONFLICT DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*) INTO chunk_inserted FROM ins;
        inserted_total := inserted_total + chunk_inserted;
        RAISE NOTICE 'chunk starting % inserted %', to_timestamp(cur_ts/1e6), chunk_inserted;
        cur_ts := cur_ts + chunk_us;
    END LOOP;
    RAISE NOTICE 'TOTAL inserted: %', inserted_total;
END
\$\$;
SQL

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
