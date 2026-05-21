#!/bin/bash
# Fill the missing window 2026-05-06 14:00 -> 2026-05-10 14:00 UTC.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

W_LO=1778076000000000   # 2026-05-06 14:00 UTC
W_HI=1778421600000000   # 2026-05-10 14:00 UTC

for ASSET in btc eth sol; do
  OUT=/tmp/${ASSET}_l25_gap_may6_may10.csv
  echo "=== $ASSET ==="
  T0=$(date +%s)
  psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 -c "\copy (SELECT o.* FROM orderbook_snapshots_v2 o WHERE o.timestamp_us BETWEEN ${W_LO} AND ${W_HI} AND o.slug LIKE '${ASSET}-updown-%' ORDER BY o.market_id, o.outcome, o.timestamp_us) TO '${OUT}' CSV HEADER"
  T1=$(date +%s)
  echo "  rows: $(wc -l < $OUT)  ($((T1-T0))s)"
  ls -la $OUT
  gzip -f $OUT
  ls -la ${OUT}.gz
done
echo
echo "=== summary ==="
ls -la /tmp/*_l25_gap_may6_may10.csv.gz
