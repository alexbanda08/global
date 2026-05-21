#!/bin/bash
# Verify whether v3/v3_1/v3_2/v3_3/v4 sleeves emit identical signal payloads.
# If they share base-signal logic but differ only in strategy_mode label,
# we'll see: same condition_id + same minute → same {reason, signal, spread_pct, ...}.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

cat > /tmp/clone.sql <<'SQL'
\echo === BTC: per-minute signal-payload comparison across v3 family ===
\echo (drop strategy_mode label and compare the rest; if a row appears once per minute, all 5 are byte-equal)
WITH normed AS (
  SELECT
    date_trunc('minute', at) AS minute,
    sleeve_id,
    -- strip the strategy_mode label and any null fields then JSON-dump
    (data - 'strategy_mode' - 'condition_id') AS payload
  FROM trading.events
  WHERE at > now() - interval '24 hours'
    AND kind = 'poly_updown_signal'
    AND sleeve_id ~ 'btc_5m_v(3|3_1|3_2|3_3|4)$'
),
grouped AS (
  SELECT minute, payload, count(DISTINCT sleeve_id) AS sleeve_count, array_agg(DISTINCT sleeve_id ORDER BY sleeve_id) AS sleeves
  FROM normed
  GROUP BY minute, payload
)
SELECT
  sleeve_count,
  count(*) AS n_minutes,
  count(*) FILTER (WHERE sleeve_count = 5) AS minutes_with_all_5_identical
FROM grouped
GROUP BY sleeve_count
ORDER BY sleeve_count;

\echo
\echo === ETH: per-minute signal-payload comparison across v3 family ===
WITH normed AS (
  SELECT
    date_trunc('minute', at) AS minute,
    sleeve_id,
    (data - 'strategy_mode' - 'condition_id') AS payload
  FROM trading.events
  WHERE at > now() - interval '24 hours'
    AND kind = 'poly_updown_signal'
    AND sleeve_id ~ 'eth_5m_v(3|3_1|3_2|3_3|4)$'
),
grouped AS (
  SELECT minute, payload, count(DISTINCT sleeve_id) AS sleeve_count
  FROM normed
  GROUP BY minute, payload
)
SELECT
  sleeve_count,
  count(*) AS n_minutes,
  count(*) FILTER (WHERE sleeve_count = 5) AS minutes_with_all_5_identical
FROM grouped
GROUP BY sleeve_count
ORDER BY sleeve_count;

\echo
\echo === SOL: same check (we expect MORE divergence — SOL v3_2 had unique behavior) ===
WITH normed AS (
  SELECT
    date_trunc('minute', at) AS minute,
    sleeve_id,
    (data - 'strategy_mode' - 'condition_id') AS payload
  FROM trading.events
  WHERE at > now() - interval '24 hours'
    AND kind = 'poly_updown_signal'
    AND sleeve_id ~ 'sol_5m_v(3|3_1|3_2|3_3|4)$'
),
grouped AS (
  SELECT minute, payload, count(DISTINCT sleeve_id) AS sleeve_count
  FROM normed
  GROUP BY minute, payload
)
SELECT
  sleeve_count,
  count(*) AS n_minutes,
  count(*) FILTER (WHERE sleeve_count = 5) AS minutes_with_all_5_identical
FROM grouped
GROUP BY sleeve_count
ORDER BY sleeve_count;

\echo
\echo === BTC: side-by-side raw payloads for 3 sample minutes ===
SELECT
  date_trunc('minute', at) AS minute,
  sleeve_id,
  data->>'signal' AS signal,
  data->>'reason' AS reason,
  data->>'spread_pct' AS spread_pct
FROM trading.events
WHERE at > now() - interval '8 hours'
  AND kind = 'poly_updown_signal'
  AND sleeve_id ~ 'btc_5m_v(3|3_1|3_2|3_3|4)$'
ORDER BY at DESC LIMIT 25;

\echo
\echo === Per-bar reason agreement matrix on BTC (last 14d) — should be 100% if clones ===
WITH base AS (
  SELECT date_trunc('minute', at) AS minute, sleeve_id, data->>'reason' AS reason
  FROM trading.events
  WHERE at > now() - interval '14 days'
    AND kind = 'poly_updown_signal'
    AND sleeve_id ~ 'btc_5m_v(3|3_1|3_2|3_3|4)$'
)
SELECT
  count(DISTINCT minute) AS unique_minutes,
  count(*) FILTER (WHERE r2 = r3) AS v3_eq_v3_3,
  count(*) FILTER (WHERE r2 = r4) AS v3_eq_v4,
  count(*) FILTER (WHERE r1 = r2) AS v3_1_eq_v3,
  count(*) FILTER (WHERE r2 = r22) AS v3_eq_v3_2
FROM (
  SELECT minute,
    max(reason) FILTER (WHERE sleeve_id LIKE '%_v3_1') AS r1,
    max(reason) FILTER (WHERE sleeve_id LIKE '%_v3') AS r2,
    max(reason) FILTER (WHERE sleeve_id LIKE '%_v3_2') AS r22,
    max(reason) FILTER (WHERE sleeve_id LIKE '%_v3_3') AS r3,
    max(reason) FILTER (WHERE sleeve_id LIKE '%_v4') AS r4
  FROM base GROUP BY minute
) p;
SQL

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -P pager=off -f /tmp/clone.sql
