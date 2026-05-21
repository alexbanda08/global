#!/bin/bash
# Investigate btc_15m_momo HOLD/HEDGE/SELL - why no resolutions in last 17h?
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

cat > /tmp/btc15.sql <<'SQL'
\echo === per-day signal/resolution timeline for btc_15m_momo (HOLD/HEDGE/SELL all 3) ===
SELECT
  date(at AT TIME ZONE 'UTC') AS day,
  sleeve_id,
  kind,
  count(*) AS n
FROM trading.events
WHERE at > now() - interval '14 days'
  AND sleeve_id IN (
    'poly_updown_btc_15m_momo_HOLD',
    'poly_updown_btc_15m_momo_HEDGE',
    'poly_updown_btc_15m_momo_SELL'
  )
GROUP BY day, sleeve_id, kind
ORDER BY day DESC, sleeve_id, kind;

\echo
\echo === per-day SIGNAL events with reason breakdown for btc_15m_momo_HOLD ===
SELECT
  date(at AT TIME ZONE 'UTC') AS day,
  count(*) FILTER (WHERE data->>'reason' = 'no_signal') AS no_signal,
  count(*) FILTER (WHERE data->>'reason' = 'wide_spread_skip') AS wide_spread,
  count(*) FILTER (WHERE data->>'reason' = 'order_placed') AS order_placed,
  count(*) FILTER (WHERE data->>'reason' = 'market_already_resolved') AS already_resolved,
  count(*) FILTER (WHERE data->>'reason' NOT IN ('no_signal','wide_spread_skip','order_placed','market_already_resolved') AND data->>'reason' IS NOT NULL) AS other,
  count(*) FILTER (WHERE data->>'signal' IN ('UP','DOWN')) AS fires,
  count(*) AS total
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_btc_15m_momo_HOLD'
GROUP BY day
ORDER BY day DESC;

\echo
\echo === last 5 resolution events for each btc_15m_momo sleeve ===
SELECT sleeve_id, at, data->>'won' AS won, data->>'pnl_usd' AS pnl
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id IN (
    'poly_updown_btc_15m_momo_HOLD',
    'poly_updown_btc_15m_momo_HEDGE',
    'poly_updown_btc_15m_momo_SELL'
  )
ORDER BY at DESC LIMIT 15;

\echo
\echo === time-gap stats: gap between consecutive resolutions per sleeve ===
WITH r AS (
  SELECT sleeve_id, at,
         lag(at) OVER (PARTITION BY sleeve_id ORDER BY at) AS prev_at
  FROM trading.events
  WHERE at > now() - interval '14 days'
    AND kind = 'poly_updown_resolution'
    AND sleeve_id IN (
      'poly_updown_btc_15m_momo_HOLD',
      'poly_updown_btc_15m_momo_HEDGE',
      'poly_updown_btc_15m_momo_SELL'
    )
)
SELECT sleeve_id,
       count(*) AS resolutions,
       min(at) AS first_at,
       max(at) AS last_at,
       round(extract(epoch from (max(at)-min(at)))/3600.0, 2) AS span_hours,
       round(avg(extract(epoch from (at-prev_at)))/3600.0, 2) AS avg_gap_h,
       round(max(extract(epoch from (at-prev_at)))/3600.0, 2) AS max_gap_h,
       extract(epoch from (now()-max(at)))/3600.0 AS hours_since_last
FROM r
GROUP BY sleeve_id
ORDER BY sleeve_id;

\echo
\echo === recent btc_15m_momo_HOLD signal payloads in last 24h (any reason) ===
SELECT at, data->>'reason' AS reason, data->>'signal' AS signal, data->>'condition_id' AS cid
FROM trading.events
WHERE at > now() - interval '24 hours'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_btc_15m_momo_HOLD'
ORDER BY at DESC LIMIT 30;

\echo
\echo === COMPARE: btc_15m_momo_v2 resolutions in last 14d (does it still fire?) ===
SELECT
  date(at AT TIME ZONE 'UTC') AS day,
  sleeve_id,
  count(*) AS n
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id IN (
    'poly_updown_btc_15m_momo_v2_HOLD',
    'poly_updown_btc_15m_momo_v2_HEDGE',
    'poly_updown_btc_15m_momo_v2_SELL'
  )
GROUP BY day, sleeve_id
ORDER BY day DESC, sleeve_id;

\echo
\echo === COMPARE: eth_15m and sol_15m momo (v1) resolutions per day ===
SELECT
  date(at AT TIME ZONE 'UTC') AS day,
  sleeve_id,
  count(*) AS n
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id ~ '_15m_momo_(HOLD|HEDGE|SELL)$'
  AND sleeve_id !~ 'btc_'
GROUP BY day, sleeve_id
ORDER BY day DESC, sleeve_id;
SQL

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -P pager=off -f /tmp/btc15.sql
