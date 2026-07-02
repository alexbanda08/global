#!/bin/bash
# Polymarket price_change DELTA pull from VPS3 storedata (orderbook_deltas_v2).
# FORWARD-ONLY — deltas only exist from when the collector was deployed (~2026-06-16). No history before that.
# Run ON vps3 (like pull_l25_topoff.sh). Bump T_START_US to your last-pulled max each refresh.
set -euo pipefail
T_START_US=${1:-0}                      # 0 = full table; or pass last-pulled max_ts_us for a top-off
TAG=2026_06_16
DIR=/tmp/v3_deltas_${TAG}
echo "== DELTAS: ts>=${T_START_US} -> NOW (tag ${TAG}) =="
mkdir -p $DIR; chmod 777 $DIR; rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true
for ASSET in btc eth sol; do
  OUT=$DIR/${ASSET}_orderbook_deltas.csv; echo "[deltas $ASSET]"; T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT timestamp_us, local_timestamp_us, market_id, slug, asset_id, outcome, outcome_id, side, price, size, hash, source FROM orderbook_deltas_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY slug, outcome, timestamp_us) TO '${OUT}' CSV HEADER"
  echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT; ls -la ${OUT}.gz
done
echo "=== deltas done ==="; ls -la $DIR/*.gz
# then scp $DIR/*.gz -> research repo data/v4/refresh_2026_06_16/raw/ and run merge_deltas.py
