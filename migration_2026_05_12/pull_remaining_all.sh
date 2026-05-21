#!/bin/bash
# Pull the 5 datasets we don't have locally:
#  - hl_liquidations FULL (5.2M rows, May 2025 -> May 2026) from VPS3 (has freshest)
#  - cryptocap_dominance_v2 (40k rows, 2014 -> 2026) from VPS3
#  - binance_metrics_v2 (315k rows, 2025 -> 2026) from VPS3
#  - hyperliquid_funding_v2 (10k rows) from VPS3
#  - hyperliquid_metrics_v2 (88k rows) from VPS3
# Also pull VPS2 trades_v2 delta (VPS2 has +1.49M rows vs VPS3 — extra captures).
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

echo "[1] hl_liquidations FULL"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_liquidations_v2 ORDER BY coin, time_exchange_us) TO '/tmp/hl_liquidations_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/hl_liquidations_full.csv)"
gzip -f /tmp/hl_liquidations_full.csv

echo "[2] cryptocap_dominance_v2 FULL"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM cryptocap_dominance_v2 ORDER BY time_period_start_us) TO '/tmp/cryptocap_dominance_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/cryptocap_dominance_full.csv)"
gzip -f /tmp/cryptocap_dominance_full.csv

echo "[3] binance_metrics_v2 FULL"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM binance_metrics_v2 ORDER BY create_time_us) TO '/tmp/binance_metrics_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/binance_metrics_full.csv)"
gzip -f /tmp/binance_metrics_full.csv

echo "[4] hyperliquid_funding_v2 FULL"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_funding_v2 ORDER BY funding_time_us) TO '/tmp/hl_funding_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/hl_funding_full.csv)"
gzip -f /tmp/hl_funding_full.csv

echo "[5] hyperliquid_metrics_v2 FULL"
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM hyperliquid_metrics_v2 ORDER BY time_exchange_us) TO '/tmp/hl_metrics_full.csv' CSV HEADER"
echo "  rows: $(wc -l < /tmp/hl_metrics_full.csv)"
gzip -f /tmp/hl_metrics_full.csv

echo
echo "=== summary ==="
ls -la /tmp/hl_liquidations_full.csv.gz /tmp/cryptocap_dominance_full.csv.gz /tmp/binance_metrics_full.csv.gz /tmp/hl_funding_full.csv.gz /tmp/hl_metrics_full.csv.gz
echo "Done $(date -u +%FT%TZ)"
