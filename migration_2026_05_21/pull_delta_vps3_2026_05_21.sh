#!/bin/bash
# Pull delta May 19 00:00 UTC -> NOW from VPS3 for all canonical sources.
# Overlaps with last refresh_2026_05_19 (which had data through ~May 19 23:35 UTC) for safety.
#
# Tables (all on VPS3 / storedata DB):
#   orderbook_snapshots_v2   -> L25 books, BTC/ETH/SOL
#   binance_klines_v2        -> 1MIN/5MIN/15MIN + 1SEC klines (binance-spot-ws)
#   oracle_prices_v2         -> chainlink RTDS feed
#   trades_v2                -> polymarket CLOB trades
#   market_resolutions_v2    -> chainlink-resolved Up/Down outcomes (full pull)
#   trading.events           -> production audit log (30d rolling, FULL pull)
#   hyperliquid_klines_v2    -> HL perp klines
#   hyperliquid_trades_v2    -> HL trades
#   hyperliquid_liquidations_v2 -> HL liqs

set -euo pipefail

# Window: 2026-05-19 00:00 UTC (overlap with last delta for safety)
T_START_US=1779235200000000          # 2026-05-19 00:00 UTC
TAG=2026_05_21
echo "==============================================="
echo " VPS3 delta pull: $(date -u -d @${T_START_US:0:10}) -> NOW"
echo " Tag: ${TAG}"
echo "==============================================="

mkdir -p /tmp/v3_delta_${TAG}
chmod 777 /tmp/v3_delta_${TAG}
rm -f /tmp/v3_delta_${TAG}/*.csv /tmp/v3_delta_${TAG}/*.gz 2>/dev/null || true

# 1. L25 orderbook delta per asset
for ASSET in btc eth sol; do
  OUT=/tmp/v3_delta_${TAG}/${ASSET}_orderbook_L25_delta_${TAG}.csv
  echo "[L25 $ASSET] from $(date -u -d @${T_START_US:0:10})"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM orderbook_snapshots_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY market_id, outcome, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
  ls -la ${OUT}.gz
done

# 2. binance klines (1MIN/5MIN/15MIN, binance-spot-ws, BTC/ETH/SOL)
OUT=/tmp/v3_delta_${TAG}/binance_klines_delta_${TAG}.csv
echo "[klines binance-spot-ws] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT') AND period_id IN ('1MIN','5MIN','15MIN') ORDER BY symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 3. binance 1SEC klines (for fine momentum + sigma)
OUT=/tmp/v3_delta_${TAG}/binance_klines_1sec_delta_${TAG}.csv
echo "[klines 1SEC] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND period_id='1SEC' ORDER BY symbol_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 4. chainlink RTDS oracle
OUT=/tmp/v3_delta_${TAG}/oracle_prices_delta_${TAG}.csv
echo "[oracle_prices_v2] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM oracle_prices_v2 WHERE timestamp_us >= ${T_START_US} ORDER BY symbol_id, timestamp_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 5. polymarket trades delta
for ASSET in btc eth sol; do
  OUT=/tmp/v3_delta_${TAG}/${ASSET}_trades_delta_${TAG}.csv
  echo "[trades $ASSET] from $(date -u -d @${T_START_US:0:10})"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM trades_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY slug, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
done

# 6. market resolutions (FULL pull — table is small, refresh entirely)
OUT=/tmp/v3_delta_${TAG}/market_resolutions_full_${TAG}.csv
echo "[market_resolutions_v2] FULL"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM market_resolutions_v2 WHERE slug ~ '^(btc|eth|sol)-updown-' ORDER BY slot_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 7. trading.events FULL 30d rolling window
OUT=/tmp/v3_delta_${TAG}/trading_events_30d.csv
echo "[trading.events 30d FULL]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT event_id, at, sleeve_id, position_id, order_id, kind, data FROM trading.events WHERE at > NOW() - INTERVAL '30 days' ORDER BY at) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 8. Hyperliquid klines + trades + liqs delta
for TAB in hyperliquid_klines_v2 hyperliquid_trades_v2 hyperliquid_liquidations_v2; do
  OUT=/tmp/v3_delta_${TAG}/${TAB}_delta_${TAG}.csv
  TS_COL="time_period_start_us"
  [[ "$TAB" == "hyperliquid_trades_v2" ]] && TS_COL="timestamp_us"
  [[ "$TAB" == "hyperliquid_liquidations_v2" ]] && TS_COL="time_exchange_us"
  echo "[$TAB] from $(date -u -d @${T_START_US:0:10})"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM ${TAB} WHERE ${TS_COL} >= ${T_START_US} ORDER BY ${TS_COL}) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
done

# 9. binance metrics (perp OI, LS ratio) — pull delta
OUT=/tmp/v3_delta_${TAG}/binance_metrics_delta_${TAG}.csv
echo "[binance_metrics_v2] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_metrics_v2 WHERE create_time_us >= ${T_START_US} ORDER BY symbol_id, create_time_us) TO '${OUT}' CSV HEADER" 2>/dev/null || echo "  (binance_metrics_v2 schema mismatch — skipping)"
[[ -f $OUT ]] && { echo "  rows: $(wc -l < $OUT)"; gzip -f $OUT; }

echo
echo "=== Delta pull summary ==="
ls -la /tmp/v3_delta_${TAG}/*.gz
echo "Done $(date -u +%FT%TZ)"
