#!/bin/bash
# Pull delta May 16 06 UTC -> NOW from VPS3 for all canonical sources.
# Local timestamps verified before script run: L25 ends 2026-05-16 06 UTC.
#
# Tables (all on VPS3 / storedata DB):
#   orderbook_snapshots_v2   -> L25 books, BTC/ETH/SOL
#   binance_klines_v2        -> 1MIN/5MIN/15MIN klines (binance-spot-ws)
#   oracle_prices_v2         -> chainlink RTDS feed
#   trades_v2                -> polymarket CLOB trades
#   market_resolutions_v2    -> chainlink-resolved Up/Down outcomes
#   trading.events           -> production audit log (30d rolling)
#   hyperliquid_klines_v2    -> HL perp klines
#   hyperliquid_trades_v2    -> HL trades
#   hyperliquid_liquidations_v2 -> HL liqs
#   binance_metrics_v2       -> binance perp OI / LS ratio

set -euo pipefail

# Window: pull from May 16 00:00 UTC (overlap with local last May 16 06 UTC for safety)
T_START_US=1778889600000000          # 2026-05-16 00:00 UTC (verified)
NOW_US=$(date +%s%N | head -c 16)
echo "==============================================="
echo " VPS3 delta pull: $(date -u -d @${T_START_US:0:10}) -> NOW"
echo "==============================================="

# Fix perms so postgres user can write
mkdir -p /tmp/v3_delta
chmod 777 /tmp/v3_delta
rm -f /tmp/v3_delta/*.csv /tmp/v3_delta/*.gz 2>/dev/null || true

# 1. L25 orderbook delta per asset
for ASSET in btc eth sol; do
  OUT=/tmp/v3_delta/${ASSET}_orderbook_L25_delta_2026_05_19.csv
  echo "[L25 $ASSET] from $(date -u -d @${T_START_US:0:10})"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM orderbook_snapshots_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY market_id, outcome, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
  ls -la ${OUT}.gz
done

# 2. binance klines (1MIN/5MIN/15MIN, binance-spot-ws, BTC/ETH/SOL)
OUT=/tmp/v3_delta/binance_klines_delta_2026_05_19.csv
echo "[klines binance-spot-ws] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT') AND period_id IN ('1MIN','5MIN','15MIN') ORDER BY symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 3. binance 1SEC klines (for fine momentum + sigma)
OUT=/tmp/v3_delta/binance_klines_1sec_delta_2026_05_19.csv
echo "[klines 1SEC] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND period_id='1SEC' ORDER BY symbol_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 4. chainlink RTDS oracle
OUT=/tmp/v3_delta/oracle_prices_delta_2026_05_19.csv
echo "[oracle_prices_v2] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM oracle_prices_v2 WHERE timestamp_us >= ${T_START_US} ORDER BY symbol_id, timestamp_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 5. polymarket trades delta
for ASSET in btc eth sol; do
  OUT=/tmp/v3_delta/${ASSET}_trades_delta_2026_05_19.csv
  echo "[trades $ASSET] from $(date -u -d @${T_START_US:0:10})"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM trades_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY slug, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
done

# 6. market resolutions (full pull — table is small ~25k rows, refresh entirely)
OUT=/tmp/v3_delta/market_resolutions_full_2026_05_19.csv
echo "[market_resolutions_v2] FULL"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM market_resolutions_v2 WHERE slug ~ '^(btc|eth|sol)-updown-' ORDER BY slot_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 7. trading.events full 30d (it's already a 30d rolling window — pull full)
OUT=/tmp/v3_delta/trading_events_30d.csv
echo "[trading.events 30d]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT event_id, at, sleeve_id, position_id, order_id, kind, data FROM trading.events WHERE at > NOW() - INTERVAL '30 days' ORDER BY at) TO '${OUT}' CSV HEADER"
T1=$(date +%s)
echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
gzip -f $OUT

# 8. Hyperliquid klines + trades + liqs delta
for TAB in hyperliquid_klines_v2 hyperliquid_trades_v2 hyperliquid_liquidations_v2; do
  OUT=/tmp/v3_delta/${TAB}_delta_2026_05_19.csv
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

# 9. binance metrics (perp OI, LS ratio) — usually slow updater, pull full
OUT=/tmp/v3_delta/binance_metrics_delta_2026_05_19.csv
echo "[binance_metrics_v2] from $(date -u -d @${T_START_US:0:10})"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_metrics_v2 WHERE create_time_us >= ${T_START_US} ORDER BY symbol_id, create_time_us) TO '${OUT}' CSV HEADER" 2>/dev/null || echo "  (binance_metrics_v2 schema mismatch — skipping)"
[[ -f $OUT ]] && { echo "  rows: $(wc -l < $OUT)"; gzip -f $OUT; }

echo
echo "=== Delta pull summary ==="
ls -la /tmp/v3_delta/*.gz
echo "Done $(date -u +%FT%TZ)"
