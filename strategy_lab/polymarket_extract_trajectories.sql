-- Per-market 10-second-bucketed trajectory for all resolved BTC markets.
-- One row per (market, 10s bucket, outcome) with YES/NO bid+ask stats.
--
-- Used for target/stop-loss simulation.

DROP TABLE IF EXISTS tmp_btc_trajectories;

CREATE TEMP TABLE tmp_btc_trajectories AS
WITH resolvable AS (
  SELECT DISTINCT
    slug,
    CASE WHEN slug LIKE 'btc-updown-5m-%' THEN '5m' ELSE '15m' END AS timeframe,
    CAST(substring(slug FROM '[0-9]+$') AS bigint) AS resolve_unix,
    CASE WHEN slug LIKE 'btc-updown-5m-%' THEN 300 ELSE 900 END AS window_span_s
  FROM orderbook_snapshots_v2
  WHERE slug ~ '^btc-updown-(5|15)m-[0-9]+$'
),
filtered AS (
  SELECT slug, timeframe, resolve_unix,
         (resolve_unix - window_span_s) AS window_start_unix
  FROM resolvable
  WHERE resolve_unix < extract(epoch FROM NOW())::bigint - 60
)
SELECT
  r.slug,
  r.timeframe,
  r.resolve_unix,
  r.window_start_unix,
  -- 10-second bucket since window_start: 0,1,2,...29 for 5m; 0..89 for 15m
  FLOOR((o.timestamp_us/1000000.0 - r.window_start_unix) / 10.0)::int AS bucket_10s,
  o.outcome,
  -- Per-bucket YES bid (first/last for realistic entry/exit), min/max for trajectory extrema
  (array_agg(o.bid_price_0 ORDER BY o.timestamp_us ASC))[1]  AS bid_first,
  (array_agg(o.bid_price_0 ORDER BY o.timestamp_us DESC))[1] AS bid_last,
  MIN(o.bid_price_0) AS bid_min,
  MAX(o.bid_price_0) AS bid_max,
  (array_agg(o.ask_price_0 ORDER BY o.timestamp_us ASC))[1]  AS ask_first,
  (array_agg(o.ask_price_0 ORDER BY o.timestamp_us DESC))[1] AS ask_last,
  MIN(o.ask_price_0) AS ask_min,
  MAX(o.ask_price_0) AS ask_max,
  COUNT(*) AS n_snaps
FROM filtered r
JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
WHERE o.timestamp_us/1000000 >= r.window_start_unix
  AND o.timestamp_us/1000000 <= r.resolve_unix + 5
  AND o.bid_price_0 IS NOT NULL
  AND o.ask_price_0 IS NOT NULL
GROUP BY r.slug, r.timeframe, r.resolve_unix, r.window_start_unix, bucket_10s, o.outcome;

SELECT timeframe, outcome, COUNT(*) AS bucket_rows, COUNT(DISTINCT slug) AS markets
FROM tmp_btc_trajectories
GROUP BY timeframe, outcome
ORDER BY timeframe, outcome;

\copy tmp_btc_trajectories TO '/tmp/btc_trajectories.csv' WITH CSV HEADER;
\echo Exported trajectory to /tmp/btc_trajectories.csv
