-- polymarket_extract_book_depth_full.sql
-- SIMPLE book_depth extract for full 12.5d window. Templated by asset only.
-- Use sed to substitute <ASSET>. Drops the 4-LEFT-JOIN slow markets logic.
--
-- Usage:
--   sed 's/<ASSET>/btc/g' polymarket_extract_book_depth_full.sql > /tmp/btc_full.sql
--   sudo -u postgres psql -d storedata -f /tmp/btc_full.sql
--
-- Outputs (on host running psql):
--   /tmp/<ASSET>_book_depth_v3_full.csv  (top-10 each side, 10s buckets)
--   /tmp/<ASSET>_markets_minimal.csv    (slug, outcome_up, window_start_unix, resolve_unix, timeframe)

\echo '=== book_depth + markets-minimal extract for <ASSET> (FULL window) ==='

-- 1) Markets minimal (no JOINs — fast)
\copy (SELECT slug, timeframe, (slot_start_us/1000000)::bigint AS window_start_unix, (slot_end_us/1000000)::bigint AS resolve_unix, CASE WHEN outcome='Up' THEN 1 ELSE 0 END AS outcome_up, strike_price, settlement_price FROM market_resolutions_v2 WHERE slug LIKE '<ASSET>-updown-%' AND outcome IS NOT NULL ORDER BY slot_start_us) TO '/tmp/<ASSET>_markets_minimal.csv' WITH CSV HEADER

\echo 'Wrote markets minimal -> /tmp/<ASSET>_markets_minimal.csv'

-- 2) Book depth — single INNER JOIN with DISTINCT ON (fast, slug-indexed)
DROP TABLE IF EXISTS tmp_book_depth_full;
CREATE TEMP TABLE tmp_book_depth_full AS
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
)
SELECT DISTINCT ON (o.slug, FLOOR((o.timestamp_us / 1000000.0 - r.window_start_unix) / 10.0)::int, o.outcome)
  o.slug,
  r.timeframe,
  r.resolve_unix,
  r.window_start_unix,
  FLOOR((o.timestamp_us / 1000000.0 - r.window_start_unix) / 10.0)::int AS bucket_10s,
  o.outcome,
  o.timestamp_us AS snap_ts_us,
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
ORDER BY o.slug, bucket_10s, o.outcome, o.timestamp_us DESC;

\echo '--- book_depth summary ---'
SELECT timeframe, outcome, COUNT(*) AS bucket_rows, COUNT(DISTINCT slug) AS markets
FROM tmp_book_depth_full
GROUP BY timeframe, outcome
ORDER BY timeframe, outcome;

\copy tmp_book_depth_full TO '/tmp/<ASSET>_book_depth_v3_full.csv' WITH CSV HEADER
\echo 'Wrote book_depth -> /tmp/<ASSET>_book_depth_v3_full.csv'

\echo '=== DONE for <ASSET> ==='
