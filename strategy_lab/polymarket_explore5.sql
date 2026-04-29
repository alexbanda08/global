-- Study one BTC 5m market's full lifecycle
\set mkt 'btc-updown-5m-1776951000'

-- 1. Resolution timestamp in human form
SELECT to_timestamp(1776951000) AS resolve_at,
       to_timestamp(1776951000 - 300) AS approx_open;

-- 2. Full price trajectory (mid + spread over time) with outcome YES only
SELECT
  to_timestamp(timestamp_us/1000000) AS ts,
  outcome,
  bid_price_0, bid_size_0,
  ask_price_0, ask_size_0,
  (bid_price_0 + ask_price_0)/2.0 AS mid,
  (ask_price_0 - bid_price_0) AS spread
FROM orderbook_snapshots_v2
WHERE slug = 'btc-updown-5m-1776951000' AND outcome = 'Up'
ORDER BY timestamp_us ASC
LIMIT 1;  -- first snapshot

-- 3. Last snapshot for same market, both sides
SELECT to_timestamp(timestamp_us/1000000) AS ts, outcome, bid_price_0, ask_price_0
FROM orderbook_snapshots_v2
WHERE slug = 'btc-updown-5m-1776951000'
ORDER BY timestamp_us DESC LIMIT 4;

-- 4. Time-bucketed trajectory: min/max/avg YES mid per minute
SELECT
  date_trunc('minute', to_timestamp(timestamp_us/1000000)) AS minute,
  outcome,
  COUNT(*) AS snaps,
  ROUND(AVG((bid_price_0 + ask_price_0)/2.0)::numeric, 4) AS avg_mid,
  ROUND(MIN((bid_price_0 + ask_price_0)/2.0)::numeric, 4) AS min_mid,
  ROUND(MAX((bid_price_0 + ask_price_0)/2.0)::numeric, 4) AS max_mid
FROM orderbook_snapshots_v2
WHERE slug = 'btc-updown-5m-1776951000'
GROUP BY minute, outcome
ORDER BY minute, outcome;

-- 5. Market lifespan across ALL BTC 5m markets (sanity check: how early do snapshots start vs close?)
SELECT slug,
  to_timestamp(MIN(timestamp_us)/1000000) AS first_snap,
  to_timestamp(MAX(timestamp_us)/1000000) AS last_snap,
  to_timestamp(CAST(substring(slug FROM '[0-9]+$') AS bigint)) AS resolve_at,
  EXTRACT(EPOCH FROM (to_timestamp(MAX(timestamp_us)/1000000) - to_timestamp(MIN(timestamp_us)/1000000)))/60.0 AS span_min
FROM orderbook_snapshots_v2
WHERE slug LIKE 'btc-updown-5m-%'
  AND CAST(substring(slug FROM '[0-9]+$') AS bigint) < extract(epoch FROM NOW())::bigint
GROUP BY slug
ORDER BY first_snap
LIMIT 5;
