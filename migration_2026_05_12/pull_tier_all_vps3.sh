#!/bin/bash
# VPS3-side pulls: 1SEC klines, polymarket trades, HL trades + liquidations,
# trading.events 30d, binance-vision archive.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

T_APR22=1777161600000000
T_NOW=$(date +%s)000000

echo "=============================================="
echo " VPS3 BACKFILL — started $(date -u +%FT%TZ)"
echo "=============================================="

### 1. binance 1SEC klines (live ws + vision archive)
echo "[1SEC klines] full"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE period_id = '1SEC' ORDER BY symbol_id, source, time_period_start_us) TO '/tmp/binance_1sec_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/binance_1sec_full.csv)"
gzip -f /tmp/binance_1sec_full.csv

### 2. binance-vision archive (1MIN/5MIN/15MIN/1HRS/4HRS/1DAY)
echo "[binance-vision] all timeframes"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_klines_v2 WHERE source = 'binance-vision' AND period_id != '1SEC' ORDER BY symbol_id, period_id, time_period_start_us) TO '/tmp/binance_vision_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/binance_vision_full.csv)"
gzip -f /tmp/binance_vision_full.csv

### 3. polymarket trades Apr 22 -> now (full window)
for ASSET in btc eth sol; do
  OUT=/tmp/${ASSET}_trades_full.csv
  echo "[trades $ASSET] Apr 22 -> now"
  T0=$(date +%s)
  psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM trades_v2 WHERE slug LIKE '${ASSET}-updown-%' AND timestamp_us BETWEEN ${T_APR22} AND ${T_NOW} ORDER BY market_id, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f $OUT
done

### 4. hyperliquid_trades_v2 (last 30d)
echo "[HL trades] 30d"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_trades_v2 WHERE time_exchange_us > (EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days') * 1e6)::bigint ORDER BY symbol_id, time_exchange_us) TO '/tmp/hl_trades_30d.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/hl_trades_30d.csv)"
gzip -f /tmp/hl_trades_30d.csv

### 5. hyperliquid_liquidations_v2 (last 30d)
echo "[HL liquidations] 30d"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_liquidations_v2 WHERE time_exchange_us > (EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days') * 1e6)::bigint ORDER BY symbol_id, time_exchange_us) TO '/tmp/hl_liquidations_30d.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/hl_liquidations_30d.csv)"
gzip -f /tmp/hl_liquidations_30d.csv

### 6. trading.events 30d
echo "[trading.events] 30d"
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT event_id, at, sleeve_id, position_id, order_id, kind, data FROM trading.events WHERE at > NOW() - INTERVAL '30 days' ORDER BY at) TO '/tmp/trading_events_30d.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/trading_events_30d.csv)"
gzip -f /tmp/trading_events_30d.csv

echo
echo "=== VPS3 backfill summary ==="
ls -la /tmp/binance_1sec_full.csv.gz /tmp/binance_vision_full.csv.gz /tmp/*_trades_full.csv.gz /tmp/hl_trades_30d.csv.gz /tmp/hl_liquidations_30d.csv.gz /tmp/trading_events_30d.csv.gz 2>/dev/null
echo "Done $(date -u +%FT%TZ)"
