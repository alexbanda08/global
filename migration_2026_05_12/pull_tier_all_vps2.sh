#!/bin/bash
# VPS2-side pulls: L25 Apr18-22, OKX klines, hyperliquid_klines.
# Outputs to /tmp on VPS2. Local script downloads.
set -euo pipefail
sudo -u postgres psql -d storedata -c "SELECT version()" >/dev/null

# Windows
T_APR18=1776816000000000   # 2026-04-18 00:00 UTC (NOTE: VPS2 earliest is Apr 18 18:07)
T_APR22=1777161600000000   # 2026-04-22 00:00 UTC

echo "=============================================="
echo " VPS2 BACKFILL — started $(date -u +%FT%TZ)"
echo "=============================================="

### 1. Orderbook L25 Apr 18 -> Apr 22 (per asset)
for ASSET in btc eth sol; do
  OUT=/tmp/${ASSET}_l25_pre_apr22.csv
  echo "[L25 $ASSET] Apr 18 -> Apr 22"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT o.* FROM orderbook_snapshots_v2 o WHERE o.timestamp_us BETWEEN ${T_APR18} AND ${T_APR22} AND o.slug LIKE '${ASSET}-updown-%' ORDER BY o.market_id, o.outcome, o.timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
  ls -la ${OUT}.gz
done

### 2. OKX klines (full table)
echo "[OKX klines] full"
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE source = 'okx-ws' ORDER BY symbol_id, period_id, time_period_start_us) TO '/tmp/okx_klines_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/okx_klines_full.csv)"
gzip -f /tmp/okx_klines_full.csv

### 3. Hyperliquid klines (full table)
echo "[HL klines] full"
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_klines_v2 ORDER BY symbol_id, period_id, time_period_start_us) TO '/tmp/hl_klines_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/hl_klines_full.csv)"
gzip -f /tmp/hl_klines_full.csv

echo
echo "=== VPS2 backfill summary ==="
ls -la /tmp/*_l25_pre_apr22.csv.gz /tmp/okx_klines_full.csv.gz /tmp/hl_klines_full.csv.gz
echo "Done $(date -u +%FT%TZ)"
