#!/bin/bash
# Discover ALL active sleeves (not just momo) and event kinds across them.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -P pager=off <<'SQL'
\echo === ALL distinct sleeve_id (last 14d) ===
SELECT sleeve_id,
       count(*) AS events,
       count(DISTINCT kind) AS kinds,
       min(at) AS first_event,
       max(at) AS last_event
FROM trading.events
WHERE at > now() - interval '14 days'
  AND sleeve_id IS NOT NULL
GROUP BY sleeve_id
ORDER BY last_event DESC;
\echo
\echo === ALL distinct kinds last 14d ===
SELECT kind, count(*) AS n, count(DISTINCT sleeve_id) AS n_sleeves
FROM trading.events
WHERE at > now() - interval '14 days'
GROUP BY kind
ORDER BY n DESC;
SQL
