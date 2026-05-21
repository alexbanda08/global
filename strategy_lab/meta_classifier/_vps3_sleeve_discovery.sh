#!/bin/bash
# Discover momo sleeves + event types using correct column names.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -P pager=off <<'SQL'
\echo === distinct event kinds last 7d (momo sleeves only) ===
SELECT kind, count(*) AS n
FROM trading.events
WHERE at > now() - interval '7 days'
  AND sleeve_id LIKE '%momo%'
GROUP BY kind
ORDER BY n DESC
LIMIT 50;
\echo
\echo === distinct momo sleeves last 14d ===
SELECT sleeve_id, count(*) AS events, min(at) AS first_event, max(at) AS last_event
FROM trading.events
WHERE at > now() - interval '14 days'
  AND sleeve_id LIKE '%momo%'
GROUP BY sleeve_id
ORDER BY sleeve_id;
\echo
\echo === sample momo event payloads (one of each kind) ===
WITH ranked AS (
  SELECT kind, sleeve_id, at, data,
         row_number() OVER (PARTITION BY kind ORDER BY at DESC) AS rn
  FROM trading.events
  WHERE at > now() - interval '24 hours'
    AND sleeve_id LIKE '%momo%'
)
SELECT kind, sleeve_id, at, jsonb_pretty(data) AS data
FROM ranked WHERE rn = 1
ORDER BY kind;
SQL
