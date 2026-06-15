#!/bin/bash
# Hyperliquid refresh from VPS3 storedata. klines/liquidations/funding/metrics = FULL snapshot
# (small); trades = last 32 days (the canonical is a 30d rolling file). NO ORDER BY (loaders
# sort on read). Output: /tmp/v3_hl/*.csv.gz
set -euo pipefail
DIR=/tmp/v3_hl; mkdir -p $DIR; chmod 777 $DIR; rm -f $DIR/*.csv $DIR/*.gz 2>/dev/null || true
TRADES_START=$(( ($(date +%s) - 32*86400) * 1000000 ))   # now - 32d in us
echo "== HL refresh (trades since $(date -u -d @$((TRADES_START/1000000)))) =="

pull() { # table  outfile  [where]
  local tbl=$1 out=$DIR/$2 where=${3:-}
  echo "[$tbl]"; T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM $tbl $where) TO '$out' CSV HEADER"
  echo "  rows: $(wc -l < $out) ($(($(date +%s)-T0))s)"; gzip -f $out
}

pull hyperliquid_klines_v2        hyperliquid_klines.csv
pull hyperliquid_liquidations_v2  hyperliquid_liquidations.csv
pull hyperliquid_funding_v2       hyperliquid_funding.csv
pull hyperliquid_metrics_v2       hyperliquid_metrics.csv
pull hyperliquid_trades_v2        hyperliquid_trades.csv "WHERE time_exchange_us >= ${TRADES_START}"

echo "=== HL done ==="; ls -la $DIR/*.gz
