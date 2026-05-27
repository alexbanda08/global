#!/bin/bash
# FULL pull of HL klines + HL liquidations from VPS3.
# These tables are small enough for a full snapshot (~1.1 GB raw CSV combined).
# Output: /tmp/v3_hl_full/{hyperliquid_klines,hyperliquid_liquidations}.csv.gz

set -euo pipefail

OUTDIR=/tmp/v3_hl_full
mkdir -p $OUTDIR
chmod 777 $OUTDIR
rm -f $OUTDIR/*.csv $OUTDIR/*.gz 2>/dev/null || true

echo "=== HL klines (full) ==="
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_klines_v2 ORDER BY symbol_id, period_id, time_period_start_us) TO '${OUTDIR}/hyperliquid_klines.csv' CSV HEADER"
T1=$(date +%s)
echo "rows: $(wc -l < $OUTDIR/hyperliquid_klines.csv)  ($((T1-T0))s)"
gzip -f $OUTDIR/hyperliquid_klines.csv

echo "=== HL liquidations (full) ==="
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_liquidations_v2 ORDER BY time_exchange_us) TO '${OUTDIR}/hyperliquid_liquidations.csv' CSV HEADER"
T1=$(date +%s)
echo "rows: $(wc -l < $OUTDIR/hyperliquid_liquidations.csv)  ($((T1-T0))s)"
gzip -f $OUTDIR/hyperliquid_liquidations.csv

echo
echo "=== Summary ==="
ls -la $OUTDIR/*.gz
echo "Done $(date -u +%FT%TZ)"
