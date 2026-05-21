#!/bin/bash
# Deeper diagnosis: full skip breakdown for ALL v3* / v4 sleeves, plus spread_pct stats.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

cat > /tmp/dd.sql <<'SQL'
\echo === FULL skip-reason breakdown for v3/v3_1/v3_2/v3_3/v4 across BTC/ETH/SOL ===
SELECT
  split_part(sleeve_id,'_',3) AS asset,
  CASE
    WHEN sleeve_id LIKE '%_v3' THEN 'v3'
    WHEN sleeve_id LIKE '%_v3_1' THEN 'v3_1'
    WHEN sleeve_id LIKE '%_v3_2' THEN 'v3_2'
    WHEN sleeve_id LIKE '%_v3_3' THEN 'v3_3'
    WHEN sleeve_id LIKE '%_v4' THEN 'v4'
  END AS family,
  count(*) FILTER (WHERE data->>'reason' = 'no_signal') AS no_signal,
  count(*) FILTER (WHERE data->>'reason' = 'wide_spread_skip') AS wide_spread,
  count(*) FILTER (WHERE data->>'reason' = 'order_placed') AS order_placed,
  count(*) FILTER (WHERE data->>'reason' = 'hedge_placed') AS hedge_placed,
  count(*) FILTER (WHERE data->>'reason' NOT IN ('no_signal','wide_spread_skip','order_placed','hedge_placed')) AS other,
  count(*) AS total
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id ~ '_5m_v(3|3_1|3_2|3_3|4)$'
GROUP BY asset, family
ORDER BY family, asset;

\echo
\echo === spread_pct stats when v3* sleeves emit UP/DOWN, by asset ===
SELECT
  split_part(sleeve_id,'_',3) AS asset,
  CASE WHEN sleeve_id LIKE '%_v3' THEN 'v3'
       WHEN sleeve_id LIKE '%_v3_1' THEN 'v3_1'
       WHEN sleeve_id LIKE '%_v3_2' THEN 'v3_2'
       WHEN sleeve_id LIKE '%_v3_3' THEN 'v3_3'
       WHEN sleeve_id LIKE '%_v4' THEN 'v4' END AS family,
  count(*) AS n,
  round(min((data->>'spread_pct')::numeric)::numeric, 4) AS spread_min,
  round(avg((data->>'spread_pct')::numeric)::numeric, 4) AS spread_avg,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY (data->>'spread_pct')::numeric)::numeric, 4) AS spread_p50,
  round(max((data->>'spread_pct')::numeric)::numeric, 4) AS spread_max
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id ~ '_5m_v(3|3_1|3_2|3_3|4)$'
  AND data->>'signal' IN ('UP','DOWN')
  AND data ? 'spread_pct'
GROUP BY asset, family
ORDER BY family, asset;

\echo
\echo === ETH v4 — any UP/DOWN at all in 14d? ===
SELECT count(*) AS fired_count,
       count(*) FILTER (WHERE data->>'reason'='no_signal') AS no_signal,
       count(*) FILTER (WHERE data->>'reason'='wide_spread_skip') AS wide_spread,
       count(*) FILTER (WHERE data->>'reason'='order_placed') AS order_placed,
       min(at) AS first_at, max(at) AS last_at
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_eth_5m_v4';

\echo === ETH v4 — sample 3 most recent payloads (any reason) ===
SELECT at, data->>'reason' AS reason, data->>'signal' AS signal, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_eth_5m_v4'
ORDER BY at DESC LIMIT 3;

\echo
\echo === v3_2 vs v3_3 clone check: per-bar signal output diff (same condition_id, same time) ===
SELECT
  v2.at AS t_v3_2,
  v2.data->>'reason' AS reason_v3_2,
  v2.data->>'signal' AS signal_v3_2,
  v3.data->>'reason' AS reason_v3_3,
  v3.data->>'signal' AS signal_v3_3,
  v2.data->>'condition_id' AS cid
FROM trading.events v2
LEFT JOIN trading.events v3
  ON v3.sleeve_id = 'poly_updown_btc_5m_v3_3'
  AND v3.kind = 'poly_updown_signal'
  AND abs(extract(epoch from (v2.at - v3.at))) < 2
WHERE v2.at > now() - interval '24 hours'
  AND v2.sleeve_id = 'poly_updown_btc_5m_v3_2'
  AND v2.kind = 'poly_updown_signal'
ORDER BY v2.at DESC LIMIT 10;

\echo
\echo === Same v3_2 vs v3_3 on FIRED bars only (signal != NONE) ===
WITH v2_fired AS (
  SELECT at, data->>'signal' AS signal, data->>'reason' AS reason, data->>'condition_id' AS cid
  FROM trading.events
  WHERE at > now() - interval '14 days'
    AND sleeve_id = 'poly_updown_btc_5m_v3_2'
    AND kind = 'poly_updown_signal'
    AND data->>'signal' IN ('UP','DOWN')
),
v3_fired AS (
  SELECT at, data->>'signal' AS signal, data->>'reason' AS reason, data->>'condition_id' AS cid
  FROM trading.events
  WHERE at > now() - interval '14 days'
    AND sleeve_id = 'poly_updown_btc_5m_v3_3'
    AND kind = 'poly_updown_signal'
    AND data->>'signal' IN ('UP','DOWN')
)
SELECT
  count(*) AS v3_2_fires,
  (SELECT count(*) FROM v3_fired) AS v3_3_fires,
  count(*) FILTER (WHERE v3_fired.cid IS NOT NULL) AS same_market_fires,
  count(*) FILTER (WHERE v2_fired.signal = v3_fired.signal AND v3_fired.cid IS NOT NULL) AS same_direction_fires
FROM v2_fired
LEFT JOIN v3_fired ON v3_fired.cid = v2_fired.cid;
SQL

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -P pager=off -f /tmp/dd.sql
