#!/bin/bash
# L25 delta top-off from VPS3. T_START = 2026-06-08 12:00 UTC (L25 max ~Jun 8 16:23-16:28 -> ~4h overlap).
set -euo pipefail
T_START_US=1780920000000000          # 2026-06-08 12:00 UTC
TAG=2026_06_11
DIR=/tmp/v3_l25_${TAG}
echo "== L25 delta: $(date -u -d @${T_START_US:0:10}) -> NOW (tag ${TAG}) =="
mkdir -p $DIR; chmod 777 $DIR; rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true
for ASSET in btc eth sol; do
  OUT=$DIR/${ASSET}_orderbook_L25.csv; echo "[L25 $ASSET]"; T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM orderbook_snapshots_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY market_id, outcome, timestamp_us) TO '${OUT}' CSV HEADER"
  echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT; ls -la ${OUT}.gz
done
echo "=== L25 done ==="; ls -la $DIR/*.gz
