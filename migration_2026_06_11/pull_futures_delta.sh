#!/bin/bash
# Cross-exchange futures delta from VPS3. T_START = 2026-06-08 12:00 UTC (futures max ~Jun 8 15:40-16:51).
set -euo pipefail
T_START_US=1780920000000000          # 2026-06-08 12:00 UTC
TAG=2026_06_11
DIR=/tmp/v3_futures_${TAG}
echo "== futures delta: $(date -u -d @${T_START_US:0:10}) -> NOW (tag ${TAG}) =="
mkdir -p $DIR; chmod 777 $DIR; rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true

OUT=$DIR/cex_futures_klines.csv; echo "[cex_futures_klines_v2]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_klines_v2 WHERE time_period_start_us >= ${T_START_US} ORDER BY exchange, symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT

OUT=$DIR/cex_futures_ticker.csv; echo "[cex_futures_ticker_v2]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_ticker_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT

OUT=$DIR/cex_futures_trades.csv; echo "[cex_futures_trades_v2]"; T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_trades_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT

for EX in gate okx; do
  OUT=$DIR/${EX}_liquidations.csv; echo "[${EX}_liquidations_v2]"; T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM ${EX}_liquidations_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY time_exchange_us) TO '${OUT}' CSV HEADER"
  echo "  rows: $(wc -l < $OUT) ($(($(date +%s)-T0))s)"; gzip -f $OUT
done
echo "=== futures done ==="; ls -la $DIR/*.gz
