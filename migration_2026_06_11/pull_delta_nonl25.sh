#!/bin/bash
# Non-L25 delta top-off from VPS3. Minimal overlap: T_START = 2026-06-08 12:00 UTC
# (canonical non-L25 max ~Jun 8 15:35-15:38 -> ~3.5h safety overlap, deduped on merge).
set -euo pipefail
T_START_US=1781146800000000          # 2026-06-11 03:00 UTC
TAG=2026_06_11
DIR=/tmp/v3_delta_${TAG}
echo "== non-L25 delta: $(date -u -d @${T_START_US:0:10}) -> NOW (tag ${TAG}) =="
mkdir -p $DIR; chmod 777 $DIR; rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true

OUT=$DIR/binance_klines_delta.csv; echo "[klines 1/5/15MIN]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT') AND period_id IN ('1MIN','5MIN','15MIN') ORDER BY symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT

OUT=$DIR/binance_klines_1sec_delta.csv; echo "[klines 1SEC]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE time_period_start_us >= ${T_START_US} AND source='binance-spot-ws' AND period_id='1SEC' ORDER BY symbol_id, time_period_start_us) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT

OUT=$DIR/oracle_prices_delta.csv; echo "[oracle_prices_v2]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM oracle_prices_v2 WHERE timestamp_us >= ${T_START_US} ORDER BY symbol_id, timestamp_us) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT

for ASSET in btc eth sol; do
  OUT=$DIR/${ASSET}_trades_delta.csv; echo "[trades $ASSET]"; T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM trades_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY slug, timestamp_us) TO '${OUT}' CSV HEADER"
  echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT
done

OUT=$DIR/market_resolutions_full.csv; echo "[market_resolutions_v2 FULL]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM market_resolutions_v2 WHERE slug ~ '^(btc|eth|sol)-updown-' ORDER BY slot_start_us) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT

OUT=$DIR/trading_events_30d.csv; echo "[trading.events 30d FULL]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT event_id, at, sleeve_id, position_id, order_id, kind, data FROM trading.events WHERE at > NOW() - INTERVAL '30 days' ORDER BY at) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT
echo "=== non-L25 done ==="; ls -la $DIR/*.gz
