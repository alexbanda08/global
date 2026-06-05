#!/bin/bash
# Resume L25 pull: wait for the orphaned btc \copy to finish, gzip it, then pull eth+sol.
set -uo pipefail
T_START_US=1779732000000000
D=/tmp/v3_2026_05_29_topoff
echo "[resume] waiting for btc orderbook copy to finish..."
while pgrep -f "orderbook_snapshots_v2.*btc-updown" >/dev/null; do sleep 10; done
echo "[resume] btc copy done; gzipping if needed"
[ -f "$D/btc_orderbook_L25_2026_05_29_topoff.csv" ] && gzip -f "$D/btc_orderbook_L25_2026_05_29_topoff.csv"
ls -la "$D"/btc_*.gz 2>&1

for ASSET in eth sol; do
  OUT=$D/${ASSET}_orderbook_L25_2026_05_29_topoff.csv
  echo "[resume][L25 $ASSET]"
  T0=$(date +%s)
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT * FROM orderbook_snapshots_v2 WHERE timestamp_us >= ${T_START_US} AND slug LIKE '${ASSET}-updown-%' ORDER BY market_id, outcome, timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s); echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  gzip -f "$OUT"
  ls -la "${OUT}.gz"
done
echo "=== all L25 gz ==="
ls -la "$D"/*.gz
echo DONE > /tmp/l25_resume.done
echo "[resume] complete $(date -u +%FT%TZ)"
