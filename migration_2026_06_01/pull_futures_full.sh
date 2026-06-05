#!/bin/bash
# Full pull of the NEW cross-exchange futures collectors from VPS3 (first canonical ingest).
# Exchanges: bitget, bybit, gate, okx. Symbols: BNB/BTC/DOGE/ETH/SOL/XRP perp-USDT.
# Tables:
#   cex_futures_klines_v2   (1MIN/5MIN/15MIN OHLCV)         ~72k rows
#   cex_futures_ticker_v2   (mark/index/last/funding/OI)    ~10.1M rows  <- big
#   cex_futures_trades_v2   (taker prints)                  ~1.76M rows
#   gate_liquidations_v2 + okx_liquidations_v2              (bybit/bitget empty)
# Skipped: cex_futures_book_v2 (0 rows — collector not storing book yet).
set -euo pipefail

TAG=2026_06_01
DIR=/tmp/v3_futures_${TAG}
echo "============================================="
echo " VPS3 futures FULL pull (new collectors)"
echo " Tag: ${TAG}"
echo "============================================="
mkdir -p $DIR
chmod 777 $DIR
rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true

# 1. klines (full)
OUT=$DIR/cex_futures_klines.csv
echo "[cex_futures_klines_v2] FULL"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_klines_v2 ORDER BY exchange, symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 2. ticker (full — funding/OI/mark, ~10M rows)
OUT=$DIR/cex_futures_ticker.csv
echo "[cex_futures_ticker_v2] FULL"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_ticker_v2 ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 3. trades (full)
OUT=$DIR/cex_futures_trades.csv
echo "[cex_futures_trades_v2] FULL"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_trades_v2 ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 4. liquidations gate + okx (bybit/bitget empty). Tag exchange via filename.
for EX in gate okx; do
  OUT=$DIR/${EX}_liquidations.csv
  echo "[${EX}_liquidations_v2] FULL"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM ${EX}_liquidations_v2 ORDER BY time_exchange_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT
done

echo
echo "=== Futures full pull summary ==="
ls -la $DIR/*.gz
echo "Done $(date -u +%FT%TZ)"
