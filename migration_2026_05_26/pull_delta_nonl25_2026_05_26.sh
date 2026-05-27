#!/bin/bash
# Non-L25 top-off from VPS3: 2026-05-25 18:00 UTC -> NOW.
# Overlaps with last main pull (which ended ~May 25 19:14-19:21 UTC) by ~1.2h for safety.
# L25 was already topped-off separately by pull_l25_topoff_2026_05_26.sh.
#
# Tables pulled:
#   binance_klines_v2  (1MIN/5MIN/15MIN + 1SEC, binance-spot-ws only)
#   oracle_prices_v2   (chainlink RTDS)
#   trades_v2          (Polymarket CLOB trades, btc/eth/sol)
#   market_resolutions_v2 (FULL pull, small table)
#   trading.events     (FULL 30d rolling)
#   hyperliquid_klines_v2 / _trades_v2 / _liquidations_v2  (column name now correct)
# Skipped:
#   binance_metrics_v2 (geoblocked on VPS3 — collector dead since 2026-04-26)

set -euo pipefail

T_START_US=1779732000000000          # 2026-05-25 18:00 UTC
TAG=2026_05_26
echo "============================================="
echo " VPS3 non-L25 top-off: $(date -u -d @${T_START_US:0:10}) -> NOW"
echo " Tag: ${TAG}"
echo "============================================="

mkdir -p /tmp/v3_delta_${TAG}
chmod 777 /tmp/v3_delta_${TAG}
rm -f /tmp/v3_delta_${TAG}/*.csv /tmp/v3_delta_${TAG}/*.gz 2>/dev/null || true

# 1. binance klines 1MIN/5MIN/15MIN
OUT=/tmp/v3_delta_${TAG}/binance_klines_delta_${TAG}.csv
echo "[klines binance-spot-ws]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT') AND period_id IN ('1MIN','5MIN','15MIN') ORDER BY symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 2. binance klines 1SEC
OUT=/tmp/v3_delta_${TAG}/binance_klines_1sec_delta_${TAG}.csv
echo "[klines 1SEC]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND period_id='1SEC' ORDER BY symbol_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 3. chainlink RTDS
OUT=/tmp/v3_delta_${TAG}/oracle_prices_delta_${TAG}.csv
echo "[oracle_prices_v2]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM oracle_prices_v2 WHERE timestamp_us >= ${T_START_US} ORDER BY symbol_id, timestamp_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 4. polymarket trades delta
for ASSET in btc eth sol; do
  OUT=/tmp/v3_delta_${TAG}/${ASSET}_trades_delta_${TAG}.csv
  echo "[trades $ASSET]"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM trades_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY slug, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
done

# 5. market resolutions (FULL pull — table small)
OUT=/tmp/v3_delta_${TAG}/market_resolutions_full_${TAG}.csv
echo "[market_resolutions_v2] FULL"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM market_resolutions_v2 WHERE slug ~ '^(btc|eth|sol)-updown-' ORDER BY slot_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 6. trading.events FULL 30d rolling
OUT=/tmp/v3_delta_${TAG}/trading_events_30d.csv
echo "[trading.events 30d FULL]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT event_id, at, sleeve_id, position_id, order_id, kind, data FROM trading.events WHERE at > NOW() - INTERVAL '30 days' ORDER BY at) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 7. Hyperliquid klines + trades + liqs (all using time_exchange_us for trades+liqs, correct now)
for TAB in hyperliquid_klines_v2 hyperliquid_trades_v2 hyperliquid_liquidations_v2; do
  OUT=/tmp/v3_delta_${TAG}/${TAB}_delta_${TAG}.csv
  TS_COL="time_period_start_us"
  [[ "$TAB" == "hyperliquid_trades_v2" ]] && TS_COL="time_exchange_us"
  [[ "$TAB" == "hyperliquid_liquidations_v2" ]] && TS_COL="time_exchange_us"
  echo "[$TAB]"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM ${TAB} WHERE ${TS_COL} >= ${T_START_US} ORDER BY ${TS_COL}) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
done

echo
echo "=== Non-L25 top-off summary ==="
ls -la /tmp/v3_delta_${TAG}/*.gz
echo "Done $(date -u +%FT%TZ)"
