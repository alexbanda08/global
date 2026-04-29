-- Cross-asset extract: replace __ASSET__ with btc/eth/sol via sed before running.
-- Output paths are hardcoded as /tmp/__ASSET___markets_v3.csv etc.

DROP TABLE IF EXISTS tmp_markets;
CREATE TEMP TABLE tmp_markets AS
WITH resolved AS (
  SELECT
    r.slug,
    r.timeframe,
    r.market_id,
    (r.slot_end_us / 1000000)::bigint   AS resolve_unix,
    (r.slot_start_us / 1000000)::bigint AS window_start_unix,
    r.outcome,
    r.strike_price,
    r.settlement_price,
    CASE WHEN r.outcome = 'Up' THEN 1 ELSE 0 END AS outcome_up
  FROM market_resolutions_v2 r
  WHERE r.slug LIKE '__ASSET__-updown-%'
    AND r.outcome IS NOT NULL
),
entry_snap AS (
  SELECT DISTINCT ON (r.slug, o.outcome)
    r.slug, o.outcome,
    o.bid_price_0 AS bid, o.ask_price_0 AS ask,
    o.bid_size_0 AS bid_size, o.ask_size_0 AS ask_size
  FROM resolved r
  JOIN orderbook_snapshots_v2 o
    ON o.slug = r.slug
   AND o.timestamp_us / 1000000 BETWEEN r.window_start_unix AND r.resolve_unix
  ORDER BY r.slug, o.outcome, o.timestamp_us ASC
),
last_snap AS (
  SELECT DISTINCT ON (r.slug, o.outcome)
    r.slug, o.outcome,
    o.bid_price_0 AS bid, o.ask_price_0 AS ask
  FROM resolved r
  JOIN orderbook_snapshots_v2 o
    ON o.slug = r.slug
   AND o.timestamp_us / 1000000 BETWEEN r.window_start_unix AND r.resolve_unix + 5
  ORDER BY r.slug, o.outcome, o.timestamp_us DESC
),
yes_extrema AS (
  SELECT r.slug,
    MAX((o.bid_price_0 + o.ask_price_0) / 2.0) AS peak_yes_mid,
    MIN((o.bid_price_0 + o.ask_price_0) / 2.0) AS trough_yes_mid,
    COUNT(*) AS n_snaps_yes
  FROM resolved r
  JOIN orderbook_snapshots_v2 o
    ON o.slug = r.slug AND o.outcome = 'Up'
   AND o.timestamp_us / 1000000 BETWEEN r.window_start_unix AND r.resolve_unix + 5
   AND o.bid_price_0 IS NOT NULL AND o.ask_price_0 IS NOT NULL
  GROUP BY r.slug
),
no_extrema AS (
  SELECT r.slug,
    MAX((o.bid_price_0 + o.ask_price_0) / 2.0) AS peak_no_mid,
    MIN((o.bid_price_0 + o.ask_price_0) / 2.0) AS trough_no_mid
  FROM resolved r
  JOIN orderbook_snapshots_v2 o
    ON o.slug = r.slug AND o.outcome = 'Down'
   AND o.timestamp_us / 1000000 BETWEEN r.window_start_unix AND r.resolve_unix + 5
   AND o.bid_price_0 IS NOT NULL AND o.ask_price_0 IS NOT NULL
  GROUP BY r.slug
)
SELECT
  r.slug, r.timeframe, r.resolve_unix, r.window_start_unix,
  to_timestamp(r.resolve_unix)      AS resolve_at,
  to_timestamp(r.window_start_unix) AS window_start_at,
  e_up.bid AS entry_yes_bid, e_up.ask AS entry_yes_ask,
  e_dn.bid AS entry_no_bid,  e_dn.ask AS entry_no_ask,
  e_up.ask_size AS entry_yes_ask_size,
  e_dn.ask_size AS entry_no_ask_size,
  ye.peak_yes_mid, ye.trough_yes_mid, ye.n_snaps_yes,
  ne.peak_no_mid,  ne.trough_no_mid,
  l_up.bid AS final_yes_bid, l_up.ask AS final_yes_ask,
  l_dn.bid AS final_no_bid,  l_dn.ask AS final_no_ask,
  r.outcome_up, r.strike_price, r.settlement_price,
  CASE WHEN r.strike_price IS NULL OR r.strike_price = 0 THEN NULL
       ELSE ABS((r.settlement_price - r.strike_price) / r.strike_price) END AS abs_move_pct
FROM resolved r
LEFT JOIN entry_snap e_up ON e_up.slug = r.slug AND e_up.outcome = 'Up'
LEFT JOIN entry_snap e_dn ON e_dn.slug = r.slug AND e_dn.outcome = 'Down'
LEFT JOIN last_snap  l_up ON l_up.slug = r.slug AND l_up.outcome = 'Up'
LEFT JOIN last_snap  l_dn ON l_dn.slug = r.slug AND l_dn.outcome = 'Down'
LEFT JOIN yes_extrema ye ON ye.slug = r.slug
LEFT JOIN no_extrema  ne ON ne.slug = r.slug;

SELECT timeframe, COUNT(*), SUM(outcome_up) AS up,
       SUM((entry_yes_ask IS NULL OR entry_no_ask IS NULL)::int) AS missing_entry,
       ROUND(AVG(entry_yes_ask)::numeric,4) AS avg_yes_ask,
       ROUND(AVG(abs_move_pct*100)::numeric,4) AS avg_move_pct
FROM tmp_markets GROUP BY timeframe ORDER BY timeframe;

\copy (SELECT * FROM tmp_markets WHERE entry_yes_ask IS NOT NULL AND entry_no_ask IS NOT NULL) TO '/tmp/__ASSET___markets_v3.csv' WITH CSV HEADER;
\echo Markets exported.

DROP TABLE IF EXISTS tmp_traj;
CREATE TEMP TABLE tmp_traj AS
WITH resolved AS (
  SELECT slug, timeframe,
         (slot_end_us/1000000)::bigint AS resolve_unix,
         (slot_start_us/1000000)::bigint AS window_start_unix
  FROM market_resolutions_v2
  WHERE slug LIKE '__ASSET__-updown-%' AND outcome IS NOT NULL
)
SELECT
  r.slug, r.timeframe, r.resolve_unix, r.window_start_unix,
  FLOOR((o.timestamp_us/1000000.0 - r.window_start_unix)/10.0)::int AS bucket_10s,
  o.outcome,
  (array_agg(o.bid_price_0 ORDER BY o.timestamp_us ASC))[1]  AS bid_first,
  (array_agg(o.bid_price_0 ORDER BY o.timestamp_us DESC))[1] AS bid_last,
  MIN(o.bid_price_0) AS bid_min, MAX(o.bid_price_0) AS bid_max,
  (array_agg(o.ask_price_0 ORDER BY o.timestamp_us ASC))[1]  AS ask_first,
  (array_agg(o.ask_price_0 ORDER BY o.timestamp_us DESC))[1] AS ask_last,
  MIN(o.ask_price_0) AS ask_min, MAX(o.ask_price_0) AS ask_max,
  COUNT(*) AS n_snaps
FROM resolved r
JOIN orderbook_snapshots_v2 o
  ON o.slug = r.slug
 AND o.timestamp_us/1000000 BETWEEN r.window_start_unix AND r.resolve_unix + 5
WHERE o.bid_price_0 IS NOT NULL AND o.ask_price_0 IS NOT NULL
GROUP BY r.slug, r.timeframe, r.resolve_unix, r.window_start_unix, bucket_10s, o.outcome;

SELECT timeframe, outcome, COUNT(*), COUNT(DISTINCT slug) FROM tmp_traj GROUP BY 1,2 ORDER BY 1,2;

\copy tmp_traj TO '/tmp/__ASSET___trajectories_v3.csv' WITH CSV HEADER;
\echo Trajectories exported.
