#!/bin/bash
# DELTA pull of cross-exchange futures collectors from VPS3.
# Exchanges: bitget, bybit, gate, okx. Symbols: BNB/BTC/DOGE/ETH/SOL/XRP perp-USDT.
# Tables:
#   cex_futures_klines_v2   (1MIN/5MIN/15MIN OHLCV)
#   cex_futures_ticker_v2   (mark/index/last/funding/OI)   <- big ~10M/run
#   cex_futures_trades_v2   (taker prints)
#   gate/okx/bybit/bitget liquidations (bybit+bitget now populated)
#   cex_futures_book_v2     (1.86M rows total since Jun 1 — pull full)
set -euo pipefail

T_START_US=1780228800000000          # 2026-05-31 12:00 UTC
TAG=2026_06_03
DIR=/tmp/v3_futures_${TAG}
echo "============================================="
echo " VPS3 futures DELTA pull"
echo " T_START_US=${T_START_US}  Tag: ${TAG}"
echo "============================================="
mkdir -p $DIR
chmod 777 $DIR
rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true

# 1. klines DELTA (time_period_start_us)
OUT=$DIR/cex_futures_klines.csv
echo "[cex_futures_klines_v2] DELTA"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_klines_v2 WHERE time_period_start_us >= ${T_START_US} ORDER BY exchange, symbol_id, period_id, time_period_start_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 2. ticker DELTA (time_exchange_us)
OUT=$DIR/cex_futures_ticker.csv
echo "[cex_futures_ticker_v2] DELTA"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_ticker_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 3. trades DELTA (time_exchange_us)
OUT=$DIR/cex_futures_trades.csv
echo "[cex_futures_trades_v2] DELTA"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_trades_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

# 4. liquidations DELTA — gate + okx (time_exchange_us); bybit + bitget now populated
for EX in gate okx bybit bitget; do
  OUT=$DIR/${EX}_liquidations.csv
  echo "[${EX}_liquidations_v2] DELTA"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM ${EX}_liquidations_v2 WHERE time_exchange_us >= ${T_START_US} ORDER BY time_exchange_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT
done

# 5. cex_futures_book_v2 FULL (1.86M rows since Jun 1 — first canonical ingest; pull full)
OUT=$DIR/cex_futures_book.csv
echo "[cex_futures_book_v2] FULL (new table)"
T0=$(date +%s)
sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cex_futures_book_v2 ORDER BY exchange, symbol_id, time_exchange_us) TO '${OUT}' CSV HEADER"
T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"; gzip -f $OUT

echo
echo "=== Futures delta pull summary ==="
ls -la $DIR/*.gz
echo "Done $(date -u +%FT%TZ)"
