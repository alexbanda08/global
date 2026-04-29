-- V3: trajectories scoped to resolved BTC markets only (driven by market_resolutions_v2).
-- Avoids unnecessary scans of currently-active markets.

DROP TABLE IF EXISTS tmp_btc_trajectories;

CREATE TEMP TABLE tmp_btc_trajectories AS
WITH resolved AS (
  SELECT
    slug,
    timeframe,
    (slot_end_us / 1000000)::bigint   AS resolve_unix,
    (slot_start_us / 1000000)::bigint AS window_start_unix
  FROM market_resolutions_v2
  WHERE slug LIKE 'btc-updown-%'
    AND outcome IS NOT NULL
)
SELECT
  r.slug,
  r.timeframe,
  r.resolve_unix,
  r.window_start_unix,
  FLOOR((o.timestamp_us / 1000000.0 - r.window_start_unix) / 10.0)::int AS bucket_10s,
  o.outcome,
  (array_agg(o.bid_price_0 ORDER BY o.timestamp_us ASC))[1]  AS bid_first,
  (array_agg(o.bid_price_0 ORDER BY o.timestamp_us DESC))[1] AS bid_last,
  MIN(o.bid_price_0) AS bid_min,
  MAX(o.bid_price_0) AS bid_max,
  (array_agg(o.ask_price_0 ORDER BY o.timestamp_us ASC))[1]  AS ask_first,
  (array_agg(o.ask_price_0 ORDER BY o.timestamp_us DESC))[1] AS ask_last,
  MIN(o.ask_price_0) AS ask_min,
  MAX(o.ask_price_0) AS ask_max,
  COUNT(*) AS n_snaps
FROM resolved r
JOIN orderbook_snapshots_v2 o
  ON o.slug = r.slug
 AND o.timestamp_us / 1000000 BETWEEN r.window_start_unix AND r.resolve_unix + 5
WHERE o.bid_price_0 IS NOT NULL
  AND o.ask_price_0 IS NOT NULL
GROUP BY r.slug, r.timeframe, r.resolve_unix, r.window_start_unix, bucket_10s, o.outcome;

SELECT timeframe, outcome, COUNT(*) AS bucket_rows, COUNT(DISTINCT slug) AS markets
FROM tmp_btc_trajectories
GROUP BY timeframe, outcome
ORDER BY timeframe, outcome;

\copy tmp_btc_trajectories TO '/tmp/btc_trajectories_v3.csv' WITH CSV HEADER;
\echo Exported trajectories_v3 to /tmp/btc_trajectories_v3.csv
