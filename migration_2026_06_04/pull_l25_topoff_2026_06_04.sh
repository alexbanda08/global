#!/bin/bash
# L25 top-off from VPS3: 2026-06-01 00:00 UTC -> NOW.
# Overlaps previous canonical (L25 max ~Jun 1 09:04-09:07) by ~9h for safety.
set -euo pipefail

T_START_US=1780272000000000          # 2026-06-01 00:00 UTC
TAG=2026_06_04_topoff
echo "============================================="
echo " VPS3 L25 top-off: $(date -u -d @${T_START_US:0:10}) -> NOW"
echo " Tag: ${TAG}"
echo "============================================="

mkdir -p /tmp/v3_${TAG}
chmod 777 /tmp/v3_${TAG}
rm -f /tmp/v3_${TAG}/*.csv /tmp/v3_${TAG}/*.gz 2>/dev/null || true

for ASSET in btc eth sol; do
  OUT=/tmp/v3_${TAG}/${ASSET}_orderbook_L25_${TAG}.csv
  echo "[L25 $ASSET]"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM orderbook_snapshots_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY market_id, outcome, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
  ls -la ${OUT}.gz
done

echo
echo "=== L25 top-off summary ==="
ls -la /tmp/v3_${TAG}/*.gz
echo "Done $(date -u +%FT%TZ)"
