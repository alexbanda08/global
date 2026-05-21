#!/bin/bash
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -P pager=off <<'SQL'
\echo === SELL resolution where sold ===
SELECT sleeve_id, at, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '7 days'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id LIKE '%momo%SELL%'
  AND (data->>'sold')::boolean IS TRUE
ORDER BY at DESC
LIMIT 2;
\echo
\echo === HEDGE resolution where hedged ===
SELECT sleeve_id, at, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '7 days'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id LIKE '%momo%HEDGE%'
  AND (data->>'hedged')::boolean IS TRUE
ORDER BY at DESC
LIMIT 2;
\echo
\echo === all distinct keys present in resolution payloads ===
SELECT DISTINCT jsonb_object_keys(data) AS k
FROM trading.events
WHERE at > now() - interval '7 days'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id LIKE '%momo%'
ORDER BY 1;
SQL
