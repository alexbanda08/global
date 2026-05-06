#!/usr/bin/env bash
# 99_run_all.sh — orchestrator: runs migrations 01..05 sequentially.
# Each is idempotent. If one fails, the rest still run unless --halt-on-error.
#
# Required env vars (must be exported BEFORE invoking):
#   PGHOST, PGPORT, PGUSER, PGDATABASE, PGPASSWORD       (VPS2 source)
#   VPS3_HOST, VPS3_PORT, VPS3_PGUSER, VPS3_PGDATABASE,  (VPS3 dest via tunnel)
#   VPS3_PGPASSWORD
#
# Usage:
#   export PGPASSWORD=xxx ; export VPS3_PGPASSWORD=yyy ; ...
#   ./99_run_all.sh             # run all 5 sequentially
#   ./99_run_all.sh 01 02 03    # only P0
#   ./99_run_all.sh --halt-on-error
#
# Safe to interrupt; each script is idempotent.

set -uo pipefail

cd "$(dirname "$0")"

# ----- arg parsing ----------------------------------------------------------
HALT=false
SCRIPTS=()
for arg in "$@"; do
    case "$arg" in
        --halt-on-error) HALT=true ;;
        01|02|03|04|05) SCRIPTS+=("0${arg#0}_*.sh") ;;
        *) echo "unknown arg: $arg"; exit 2 ;;
    esac
done
if [ ${#SCRIPTS[@]} -eq 0 ]; then
    SCRIPTS=(01_*.sh 02_*.sh 03_*.sh 04_*.sh 05_*.sh)
fi

# ----- pre-flight checks ----------------------------------------------------
echo "==============================================================="
echo " VPS2 -> VPS3 migration — $(date -u +%FT%TZ)"
echo "==============================================================="
echo "Source:  $PGHOST:$PGPORT/$PGDATABASE as $PGUSER"
echo "Sink:    $VPS3_HOST:$VPS3_PORT/$VPS3_PGDATABASE as $VPS3_PGUSER"
echo

# Test source connectivity
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c 'SELECT 1' >/dev/null \
    || { echo "FAIL: cannot connect to VPS2 postgres"; exit 1; }

# Test sink connectivity
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -c 'SELECT 1' >/dev/null \
    || { echo "FAIL: cannot connect to VPS3 postgres via tunnel"; exit 1; }

echo "Both endpoints reachable."
echo

# ----- run each migration ---------------------------------------------------
TOTAL_START=$(date +%s)
RESULTS=()

for pattern in "${SCRIPTS[@]}"; do
    for script in $pattern; do
        if [ ! -f "$script" ]; then
            echo "WARN: $pattern matched no file"; continue
        fi
        echo
        echo "---------------------------------------------------------------"
        echo " RUNNING: $script"
        echo "---------------------------------------------------------------"
        STEP_START=$(date +%s)
        if bash "$script"; then
            STEP_END=$(date +%s)
            ELAPSED=$((STEP_END - STEP_START))
            RESULTS+=("OK  $script  (${ELAPSED}s)")
            echo "✓ $script done in ${ELAPSED}s"
        else
            STEP_END=$(date +%s)
            ELAPSED=$((STEP_END - STEP_START))
            RESULTS+=("FAIL $script (${ELAPSED}s)")
            echo "✗ $script FAILED after ${ELAPSED}s"
            if $HALT; then
                echo "halting due to --halt-on-error"
                break 2
            fi
        fi
    done
done

TOTAL_END=$(date +%s)
TOTAL_ELAPSED=$((TOTAL_END - TOTAL_START))

# ----- summary --------------------------------------------------------------
echo
echo "==============================================================="
echo " SUMMARY  (total $((TOTAL_ELAPSED/60))m $((TOTAL_ELAPSED%60))s)"
echo "==============================================================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo
echo "==============================================================="
echo " Post-migration row counts"
echo "==============================================================="
PGPASSWORD="$VPS3_PGPASSWORD" psql -h "$VPS3_HOST" -p "$VPS3_PORT" -U "$VPS3_PGUSER" -d "$VPS3_PGDATABASE" -c "
SELECT 'hyperliquid_liquidations_v2' AS tbl, COUNT(*) FROM hyperliquid_liquidations_v2
UNION ALL SELECT 'oracle_prices_v2', COUNT(*) FROM oracle_prices_v2
UNION ALL SELECT 'markets', COUNT(*) FROM markets
UNION ALL SELECT 'trades_v2', COUNT(*) FROM trades_v2
UNION ALL SELECT 'orderbook_snapshots_v2', COUNT(*) FROM orderbook_snapshots_v2
ORDER BY tbl;
"
echo
echo "DONE: $(date -u +%FT%TZ)"
