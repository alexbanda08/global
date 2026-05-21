#!/bin/bash
# Pull L25 for May 14 00:00 → May 17 00:00 UTC, filtered by asset slug pattern.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

W_LO=1778716800000000   # 2026-05-14 00:00 UTC
W_HI=1778976000000000   # 2026-05-17 00:00 UTC

for ASSET in btc eth sol; do
  OUT=/tmp/${ASSET}_l25_full_window.csv
  echo "=== $ASSET ==="
  psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT o.* FROM orderbook_snapshots_v2 o WHERE o.timestamp_us BETWEEN ${W_LO} AND ${W_HI} AND o.slug LIKE '${ASSET}-updown-%' ORDER BY o.market_id, o.outcome, o.timestamp_us) TO '${OUT}' CSV HEADER"
  echo "  rows: $(wc -l < $OUT)"
  ls -la $OUT
  gzip -f $OUT
  ls -la ${OUT}.gz
done
echo
echo "=== summary ==="
ls -la /tmp/*_l25_full_window.csv.gz
