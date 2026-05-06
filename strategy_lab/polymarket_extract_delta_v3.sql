-- polymarket_extract_delta_v3.sql
-- Templated delta extract: tokens <ASSET> and <CUTOFF> replaced via sed
-- before psql sees the file. Avoids psql -v quoting issues.
--
-- Usage:
--   sed 's/<ASSET>/btc/g; s/<CUTOFF>/1777491000000000/g' \
--     polymarket_extract_delta_v3.sql > /tmp/btc_extract.sql
--   sudo -u postgres psql -d storedata -f /tmp/btc_extract.sql
--
-- Outputs (on the host running psql):
--   /tmp/<ASSET>_markets_v3_delta.csv
--   /tmp/<ASSET>_trajectories_v3_delta.csv
--   /tmp/<ASSET>_book_depth_v3_delta.csv

\echo '=== DELTA EXTRACT for <ASSET> (cutoff <CUTOFF>) ==='

------------------------------------------------------------
-- 1) markets_v3 delta
------------------------------------------------------------
DROP TABLE IF EXISTS tmp_markets_delta;
CREATE TEMP TABLE tmp_markets_delta AS
WITH resolved AS (
  SELECT
    r.slug,
    r.timeframe,
    r.market_id,
    (r.slot_end_us   / 1000000)::bigint AS resolve_unix,
    (r.slot_start_us / 1000000)::bigint AS window_start_unix,
    r.outcome,
    r.strike_price,
    r.settlement_price,
    CASE WHEN r.outcome = 'Up' THEN 1 ELSE 0 END AS outcome_up
  FROM market_resolutions_v2 r
  WHERE r.slug LIKE '<ASSET>-updown-%'
    AND r.outcome IS NOT NULL
    AND r.slot_start_us > <CUTOFF>
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
    ON o.slug = r.slug
   AND o.outcome = 'Up'
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
    ON o.slug = r.slug
   AND o.outcome = 'Down'
   AND o.timestamp_us / 1000000 BETWEEN r.window_start_unix AND r.resolve_unix + 5
   AND o.bid_price_0 IS NOT NULL AND o.ask_price_0 IS NOT NULL
  GROUP BY r.slug
)
SELECT
  r.slug,
  r.timeframe,
  r.resolve_unix,
  r.window_start_unix,
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
  r.outcome_up,
  r.strike_price,
  r.settlement_price,
  CASE
    WHEN r.strike_price IS NULL OR r.strike_price = 0 THEN NULL
    ELSE ABS((r.settlement_price - r.strike_price) / r.strike_price)
  END AS abs_move_pct
FROM resolved r
LEFT JOIN entry_snap e_up ON e_up.slug = r.slug AND e_up.outcome = 'Up'
LEFT JOIN entry_snap e_dn ON e_dn.slug = r.slug AND e_dn.outcome = 'Down'
LEFT JOIN last_snap  l_up ON l_up.slug = r.slug AND l_up.outcome = 'Up'
LEFT JOIN last_snap  l_dn ON l_dn.slug = r.slug AND l_dn.outcome = 'Down'
LEFT JOIN yes_extrema ye  ON ye.slug = r.slug
LEFT JOIN no_extrema  ne  ON ne.slug = r.slug;

\echo '--- markets_v3 delta summary ---'
SELECT timeframe,
  COUNT(*) AS markets,
  SUM(outcome_up) AS up_wins,
  COUNT(*) - SUM(outcome_up) AS down_wins,
  SUM((entry_yes_ask IS NULL OR entry_no_ask IS NULL)::int) AS missing_entry,
  ROUND(AVG(entry_yes_ask)::numeric, 4) AS avg_yes_ask,
  ROUND(AVG(entry_no_ask)::numeric, 4)  AS avg_no_ask
FROM tmp_markets_delta
GROUP BY timeframe
ORDER BY timeframe;

\copy (SELECT * FROM tmp_markets_delta WHERE entry_yes_ask IS NOT NULL AND entry_no_ask IS NOT NULL) TO '/tmp/<ASSET>_markets_v3_delta.csv' WITH CSV HEADER
\echo 'Wrote markets delta -> /tmp/<ASSET>_markets_v3_delta.csv'

------------------------------------------------------------
-- 2) trajectories_v3 delta
------------------------------------------------------------
DROP TABLE IF EXISTS tmp_traj_delta;
CREATE TEMP TABLE tmp_traj_delta AS
WITH resolved AS (
  SELECT
    slug,
    timeframe,
    (slot_end_us / 1000000)::bigint   AS resolve_unix,
    (slot_start_us / 1000000)::bigint AS window_start_unix
  FROM market_resolutions_v2
  WHERE slug LIKE '<ASSET>-updown-%'
    AND outcome IS NOT NULL
    AND slot_start_us > <CUTOFF>
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

\echo '--- trajectories_v3 delta summary ---'
SELECT timeframe, outcome, COUNT(*) AS bucket_rows, COUNT(DISTINCT slug) AS markets
FROM tmp_traj_delta
GROUP BY timeframe, outcome
ORDER BY timeframe, outcome;

\copy tmp_traj_delta TO '/tmp/<ASSET>_trajectories_v3_delta.csv' WITH CSV HEADER
\echo 'Wrote trajectories delta -> /tmp/<ASSET>_trajectories_v3_delta.csv'

------------------------------------------------------------
-- 3) book_depth_v3 delta (top-10 each side, last snap per 10s bucket)
------------------------------------------------------------
DROP TABLE IF EXISTS tmp_book_depth_delta;
CREATE TEMP TABLE tmp_book_depth_delta AS
WITH resolved AS (
  SELECT
    slug,
    timeframe,
    (slot_end_us   / 1000000)::bigint AS resolve_unix,
    (slot_start_us / 1000000)::bigint AS window_start_unix,
    slot_start_us  AS window_start_us,
    slot_end_us    AS resolve_us
  FROM market_resolutions_v2
  WHERE slug LIKE '<ASSET>-updown-%'
    AND outcome IS NOT NULL
    AND slot_start_us > <CUTOFF>
),
bucketed AS (
  SELECT
    r.slug,
    r.timeframe,
    r.resolve_unix,
    r.window_start_unix,
    FLOOR((o.timestamp_us / 1000000.0 - r.window_start_unix) / 10.0)::int AS bucket_10s,
    o.outcome,
    o.timestamp_us,
    o.bid_price_0, o.bid_size_0,
    o.bid_price_1, o.bid_size_1,
    o.bid_price_2, o.bid_size_2,
    o.bid_price_3, o.bid_size_3,
    o.bid_price_4, o.bid_size_4,
    o.bid_price_5, o.bid_size_5,
    o.bid_price_6, o.bid_size_6,
    o.bid_price_7, o.bid_size_7,
    o.bid_price_8, o.bid_size_8,
    o.bid_price_9, o.bid_size_9,
    o.ask_price_0, o.ask_size_0,
    o.ask_price_1, o.ask_size_1,
    o.ask_price_2, o.ask_size_2,
    o.ask_price_3, o.ask_size_3,
    o.ask_price_4, o.ask_size_4,
    o.ask_price_5, o.ask_size_5,
    o.ask_price_6, o.ask_size_6,
    o.ask_price_7, o.ask_size_7,
    o.ask_price_8, o.ask_size_8,
    o.ask_price_9, o.ask_size_9
  FROM resolved r
  JOIN orderbook_snapshots_v2 o
    ON o.slug = r.slug
   AND o.timestamp_us BETWEEN r.window_start_us AND r.resolve_us + 5000000
  WHERE o.bid_price_0 IS NOT NULL
    AND o.ask_price_0 IS NOT NULL
)
SELECT DISTINCT ON (slug, bucket_10s, outcome)
  slug, timeframe, resolve_unix, window_start_unix, bucket_10s, outcome, timestamp_us AS snap_ts_us,
  bid_price_0, bid_size_0,
  bid_price_1, bid_size_1,
  bid_price_2, bid_size_2,
  bid_price_3, bid_size_3,
  bid_price_4, bid_size_4,
  bid_price_5, bid_size_5,
  bid_price_6, bid_size_6,
  bid_price_7, bid_size_7,
  bid_price_8, bid_size_8,
  bid_price_9, bid_size_9,
  ask_price_0, ask_size_0,
  ask_price_1, ask_size_1,
  ask_price_2, ask_size_2,
  ask_price_3, ask_size_3,
  ask_price_4, ask_size_4,
  ask_price_5, ask_size_5,
  ask_price_6, ask_size_6,
  ask_price_7, ask_size_7,
  ask_price_8, ask_size_8,
  ask_price_9, ask_size_9
FROM bucketed
ORDER BY slug, bucket_10s, outcome, timestamp_us DESC;

\echo '--- book_depth_v3 delta summary ---'
SELECT timeframe, outcome, COUNT(*) AS bucket_rows, COUNT(DISTINCT slug) AS markets
FROM tmp_book_depth_delta
GROUP BY timeframe, outcome
ORDER BY timeframe, outcome;

\copy tmp_book_depth_delta TO '/tmp/<ASSET>_book_depth_v3_delta.csv' WITH CSV HEADER
\echo 'Wrote book_depth delta -> /tmp/<ASSET>_book_depth_v3_delta.csv'

\echo '=== DONE for <ASSET> ==='
