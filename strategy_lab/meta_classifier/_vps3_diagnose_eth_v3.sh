#!/bin/bash
# Diagnose why eth_5m_v3* and v4 sleeves rarely fire.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

cat > /tmp/d.sql <<'SQL'
\echo === skip reasons per sleeve last 7d (ETH 5m v3 family vs BTC v3 vs SOL v3 vs ETH momo) ===
SELECT sleeve_id,
       data->>'reason' AS reason,
       count(*) AS n
FROM trading.events
WHERE at > now() - interval '7 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id IN (
    'poly_updown_eth_5m_v3','poly_updown_eth_5m_v3_1','poly_updown_eth_5m_v3_2',
    'poly_updown_eth_5m_v3_3','poly_updown_eth_5m_v4',
    'poly_updown_btc_5m_v3','poly_updown_sol_5m_v3',
    'poly_updown_eth_5m_momo_HOLD','poly_updown_eth_5m_momo_v2_HOLD')
GROUP BY sleeve_id, reason
ORDER BY sleeve_id, n DESC;

\echo
\echo === all distinct signal-payload keys present for ETH v3 family ===
SELECT DISTINCT jsonb_object_keys(data) AS k
FROM trading.events
WHERE at > now() - interval '7 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id LIKE 'poly_updown_eth_5m_v%'
ORDER BY 1;

\echo
\echo === sample SKIPPED ETH v3 signal (signal=NONE) ===
SELECT sleeve_id, at, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '24 hours'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_eth_5m_v3'
  AND data->>'signal' = 'NONE'
ORDER BY at DESC LIMIT 1;

\echo === sample FIRED ETH v3 signal (signal=UP/DOWN) ===
SELECT sleeve_id, at, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '14 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_eth_5m_v3'
  AND data->>'signal' IN ('UP','DOWN')
ORDER BY at DESC LIMIT 1;

\echo === sample SKIPPED ETH v4 signal ===
SELECT sleeve_id, at, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '24 hours'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_eth_5m_v4'
  AND data->>'signal' = 'NONE'
ORDER BY at DESC LIMIT 1;

\echo === sample SKIPPED ETH v3_1 signal ===
SELECT sleeve_id, at, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '24 hours'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_eth_5m_v3_1'
  AND data->>'signal' = 'NONE'
ORDER BY at DESC LIMIT 1;

\echo === for comparison: sample SKIPPED BTC v3 signal ===
SELECT sleeve_id, at, jsonb_pretty(data) AS data
FROM trading.events
WHERE at > now() - interval '24 hours'
  AND kind = 'poly_updown_signal'
  AND sleeve_id = 'poly_updown_btc_5m_v3'
  AND data->>'signal' = 'NONE'
ORDER BY at DESC LIMIT 1;
SQL

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -P pager=off -f /tmp/d.sql
