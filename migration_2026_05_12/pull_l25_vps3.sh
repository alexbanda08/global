#!/bin/bash
# Pull full L25 orderbook history from VPS3 for May 8 - May 15 (UTC).
# Uses tradingvenue_ro user via tv-ro.env (no sudo).
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

W_LO=1778025600000000   # May 7 00:00 UTC
W_HI=1778889600000000   # May 16 00:00 UTC

for ASSET in btc eth sol; do
  MIDS=/tmp/_l25_pull_mids_${ASSET}.txt
  OUT=/tmp/${ASSET}_l25_full.csv
  echo "=== $ASSET ==="
  psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -v ON_ERROR_STOP=1 <<SQL
DROP TABLE IF EXISTS pg_temp.pull_mids;
CREATE TEMP TABLE pull_mids (market_id text);
\copy pull_mids FROM '${MIDS}'
SELECT count(*) AS mids_loaded FROM pull_mids;
\copy (SELECT o.* FROM orderbook_snapshots_v2 o JOIN pull_mids p ON o.market_id = p.market_id WHERE o.timestamp_us BETWEEN ${W_LO} AND ${W_HI} ORDER BY o.market_id, o.outcome, o.timestamp_us) TO '${OUT}' CSV HEADER
SQL
  echo "  rows: $(wc -l < $OUT)"
  ls -la $OUT
  gzip -f $OUT
  ls -la ${OUT}.gz
done
echo
echo "=== summary ==="
ls -la /tmp/*_l25_full.csv.gz
