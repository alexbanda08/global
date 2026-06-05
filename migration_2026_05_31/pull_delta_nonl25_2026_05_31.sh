#!/bin/bash
# Non-L25 top-off from VPS3: 2026-05-29 00:00 UTC -> NOW.
# Overlaps previous canonical (max ~May 29 13:17) by ~13h for safety.
set -euo pipefail

T_START_US=1780012800000000          # 2026-05-29 00:00 UTC
TAG=2026_05_31
echo "============================================="
echo " VPS3 non-L25 top-off: $(date -u -d @${T_START_US:0:10}) -> NOW"
echo " Tag: ${TAG}"
echo "============================================="

mkdir -p /tmp/v3_delta_${TAG}
chmod 777 /tmp/v3_delta_${TAG}
rm -f /tmp/v3_delta_${TAG}/*.csv /tmp/v3_delta_${TAG}/*.gz 2>/dev/null || true

# 1. binance klines 1MIN/5MIN/15MIN
OUT=/tmp/v3_delta_${TAG}/binance_klines_delta_${TAG}.csv
echo "[klines 1MIN/5MIN/15MIN]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT') AND period_id IN ('1MIN','5MIN','15MIN') ORDER BY symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 2. binance 1SEC
OUT=/tmp/v3_delta_${TAG}/binance_klines_1sec_delta_${TAG}.csv
echo "[klines 1SEC]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND period_id='1SEC' ORDER BY symbol_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 3. chainlink RTDS
OUT=/tmp/v3_delta_${TAG}/oracle_prices_delta_${TAG}.csv
echo "[oracle_prices_v2]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM oracle_prices_v2 WHERE timestamp_us >= ${T_START_US} ORDER BY symbol_id, timestamp_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 4. polymarket trades
for ASSET in btc eth sol; do
  OUT=/tmp/v3_delta_${TAG}/${ASSET}_trades_delta_${TAG}.csv
  echo "[trades $ASSET]"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM trades_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY slug, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT
done

# 5. market_resolutions full
OUT=/tmp/v3_delta_${TAG}/market_resolutions_full_${TAG}.csv
echo "[market_resolutions_v2] FULL"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM market_resolutions_v2 WHERE slug ~ '^(btc|eth|sol)-updown-' ORDER BY slot_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 6. trading.events 30d FULL rolling
OUT=/tmp/v3_delta_${TAG}/trading_events_30d.csv
echo "[trading.events 30d FULL]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT event_id, at, sleeve_id, position_id, order_id, kind, data FROM trading.events WHERE at > NOW() - INTERVAL '30 days' ORDER BY at) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

echo
echo "=== Non-L25 top-off summary ==="
ls -la /tmp/v3_delta_${TAG}/*.gz
echo "Done $(date -u +%FT%TZ)"
