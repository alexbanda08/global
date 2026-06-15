#!/bin/bash
# Cross-exchange futures DELTA top-off from VPS3: 2026-06-01 00:00 UTC -> NOW.
# Incremental now (canonical already has first ingest from 2026-06-01). Overlaps
# previous canonical (futures max ~Jun 1 09:04-09:11) by ~9h for safety.
# Tables: cex_futures_klines/ticker/trades + gate/okx liquidations.
# (book empty, bybit/bitget liq empty — skipped.)
set -euo pipefail

T_START_US=1780531200000000          # 2026-06-04 00:00 UTC
TAG=2026_06_08
DIR=/tmp/v3_futures_${TAG}
echo "============================================="
echo " VPS3 futures DELTA: $(date -u -d @${T_START_US:0:10}) -> NOW"
echo " Tag: ${TAG}"
echo "============================================="
mkdir -p $DIR; chmod 777 $DIR
rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true

# 1. klines delta
OUT=$DIR/cex_futures_klines.csv
echo "[cex_futures_klines_v2]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_klines_v2 WHERE time_period_start_us >= ${T_START_US} ORDER BY exchange, symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 2. ticker delta (funding/OI/mark — big)
OUT=$DIR/cex_futures_ticker.csv
echo "[cex_futures_ticker_v2]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_ticker_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 3. trades delta
OUT=$DIR/cex_futures_trades.csv
echo "[cex_futures_trades_v2]"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_trades_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 4. liquidations gate + okx delta
for EX in gate okx; do
  OUT=$DIR/${EX}_liquidations.csv
  echo "[${EX}_liquidations_v2]"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM ${EX}_liquidations_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY time_exchange_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT
done

echo
echo "=== Futures delta summary ==="
ls -la $DIR/*.gz
echo "Done $(date -u +%FT%TZ)"
