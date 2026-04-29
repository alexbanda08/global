-- polymarket_extract_book_depth.sql
-- Extract top-10 levels of bid+ask per (slug, 10s bucket, outcome) for resolved markets.
-- Slug-scoped via market_resolutions_v2 → uses orderbook_snapshots_v2_slug_ts_idx.
-- Captures the LAST snapshot in each 10s bucket (most recent state at bucket end).
--
-- Asset-template: replace 'btc-updown-%' with 'eth-updown-%' or 'sol-updown-%'.
-- Output: /tmp/{asset}_book_depth_v3.csv  (set ASSET below)
--
-- Safety: each row is index-bound by slug → no full table scans.
--         No interference with live collector regardless of timestamp range.

\set ASSET 'btc'
\set ASSET_PREFIX 'btc-updown-%'

DROP TABLE IF EXISTS tmp_book_depth;

CREATE TEMP TABLE tmp_book_depth AS
WITH resolved AS (
  SELECT
    slug,
    timeframe,
    (slot_end_us   / 1000000)::bigint AS resolve_unix,
    (slot_start_us / 1000000)::bigint AS window_start_unix,
    slot_start_us  AS window_start_us,
    slot_end_us    AS resolve_us
  FROM market_resolutions_v2
  WHERE slug LIKE :'ASSET_PREFIX'
    AND outcome IS NOT NULL
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

SELECT timeframe, outcome, COUNT(*) AS bucket_rows, COUNT(DISTINCT slug) AS markets
FROM tmp_book_depth
GROUP BY timeframe, outcome
ORDER BY timeframe, outcome;

\copy tmp_book_depth TO '/tmp/book_depth_v3.csv' WITH CSV HEADER;
\echo Exported book_depth_v3 to /tmp/book_depth_v3.csv
