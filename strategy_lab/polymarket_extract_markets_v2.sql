-- V2: fix outcome detection by checking BOTH sides' final bid+ask.
-- Also fix entry snapshot to use the first-in-window snap per side.

DROP TABLE IF EXISTS tmp_btc_markets;
CREATE TEMP TABLE tmp_btc_markets AS
WITH parsed AS (
  SELECT DISTINCT
    slug,
    CASE WHEN slug LIKE 'btc-updown-5m-%' THEN '5m' ELSE '15m' END AS timeframe,
    CAST(substring(slug FROM '[0-9]+$') AS bigint) AS resolve_unix,
    CASE WHEN slug LIKE 'btc-updown-5m-%' THEN 300 ELSE 900 END AS window_span_s
  FROM orderbook_snapshots_v2
  WHERE slug ~ '^btc-updown-(5|15)m-[0-9]+$'
),
resolvable AS (
  SELECT slug, timeframe, resolve_unix, window_span_s,
         (resolve_unix - window_span_s) AS window_start_unix
  FROM parsed
  WHERE resolve_unix < extract(epoch FROM NOW())::bigint - 60  -- extra 60s buffer so resolution settled
),
-- First snapshot inside [window_start, resolve_unix] per (slug, outcome)
entry_snap AS (
  SELECT DISTINCT ON (r.slug, o.outcome)
    r.slug, o.outcome,
    o.timestamp_us,
    o.bid_price_0 AS bid, o.ask_price_0 AS ask,
    o.bid_size_0 AS bid_size, o.ask_size_0 AS ask_size
  FROM resolvable r
  JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
  WHERE o.timestamp_us/1000000 >= r.window_start_unix
    AND o.timestamp_us/1000000 <= r.resolve_unix
  ORDER BY r.slug, o.outcome, o.timestamp_us ASC
),
-- Last snapshot per (slug, outcome), restricting to AFTER window_start (skip the pre-window idle period)
last_snap AS (
  SELECT DISTINCT ON (r.slug, o.outcome)
    r.slug, o.outcome,
    o.bid_price_0 AS bid, o.ask_price_0 AS ask,
    o.timestamp_us
  FROM resolvable r
  JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
  WHERE o.timestamp_us/1000000 >= r.window_start_unix
  ORDER BY r.slug, o.outcome, o.timestamp_us DESC
),
-- Trajectory extrema during the 5m/15m window (both sides for symmetric strategies)
yes_extrema AS (
  SELECT r.slug,
    MAX((o.bid_price_0 + o.ask_price_0)/2.0) AS peak_yes_mid,
    MIN((o.bid_price_0 + o.ask_price_0)/2.0) AS trough_yes_mid,
    COUNT(*) AS n_snaps_yes
  FROM resolvable r
  JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
  WHERE o.outcome = 'Up'
    AND o.timestamp_us/1000000 >= r.window_start_unix
    AND o.timestamp_us/1000000 <= r.resolve_unix + 10
    AND o.bid_price_0 IS NOT NULL AND o.ask_price_0 IS NOT NULL
  GROUP BY r.slug
),
no_extrema AS (
  SELECT r.slug,
    MAX((o.bid_price_0 + o.ask_price_0)/2.0) AS peak_no_mid,
    MIN((o.bid_price_0 + o.ask_price_0)/2.0) AS trough_no_mid
  FROM resolvable r
  JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
  WHERE o.outcome = 'Down'
    AND o.timestamp_us/1000000 >= r.window_start_unix
    AND o.timestamp_us/1000000 <= r.resolve_unix + 10
    AND o.bid_price_0 IS NOT NULL AND o.ask_price_0 IS NOT NULL
  GROUP BY r.slug
)
SELECT
  r.slug, r.timeframe, r.resolve_unix, r.window_start_unix,
  to_timestamp(r.resolve_unix) AS resolve_at,
  to_timestamp(r.window_start_unix) AS window_start_at,
  -- Entry prices at window start
  e_up.bid AS entry_yes_bid, e_up.ask AS entry_yes_ask,
  e_dn.bid AS entry_no_bid,  e_dn.ask AS entry_no_ask,
  e_up.ask_size AS entry_yes_ask_size,
  e_dn.ask_size AS entry_no_ask_size,
  -- Trajectory
  ye.peak_yes_mid, ye.trough_yes_mid, ye.n_snaps_yes,
  ne.peak_no_mid,  ne.trough_no_mid,
  -- Final prices
  l_up.bid AS final_yes_bid, l_up.ask AS final_yes_ask,
  l_dn.bid AS final_no_bid,  l_dn.ask AS final_no_ask,
  -- Outcome determination: use GREATEST of the non-null bids on each side
  CASE
    WHEN COALESCE(l_up.bid, 0) >= 0.9 AND COALESCE(l_dn.bid, 1) <= 0.1 THEN 1   -- UP won
    WHEN COALESCE(l_dn.bid, 0) >= 0.9 AND COALESCE(l_up.bid, 1) <= 0.1 THEN 0   -- DOWN won
    WHEN COALESCE(l_up.bid, 0) >= 0.9 THEN 1                                    -- UP bid high (even if Down side snapshot stale)
    WHEN COALESCE(l_dn.bid, 0) >= 0.9 THEN 0                                    -- DOWN bid high
    WHEN COALESCE(l_up.bid, 1) <= 0.05 THEN 0                                   -- UP bid very low
    WHEN COALESCE(l_dn.bid, 1) <= 0.05 THEN 1                                   -- DOWN bid very low
    ELSE NULL
  END AS outcome_up
FROM resolvable r
LEFT JOIN entry_snap e_up ON e_up.slug = r.slug AND e_up.outcome = 'Up'
LEFT JOIN entry_snap e_dn ON e_dn.slug = r.slug AND e_dn.outcome = 'Down'
LEFT JOIN last_snap  l_up ON l_up.slug = r.slug AND l_up.outcome = 'Up'
LEFT JOIN last_snap  l_dn ON l_dn.slug = r.slug AND l_dn.outcome = 'Down'
LEFT JOIN yes_extrema ye ON ye.slug = r.slug
LEFT JOIN no_extrema  ne ON ne.slug = r.slug;

-- Summary
SELECT timeframe,
  COUNT(*) AS markets,
  SUM(CASE WHEN outcome_up = 1 THEN 1 ELSE 0 END) AS up_wins,
  SUM(CASE WHEN outcome_up = 0 THEN 1 ELSE 0 END) AS down_wins,
  SUM(CASE WHEN outcome_up IS NULL THEN 1 ELSE 0 END) AS ambiguous,
  ROUND(AVG(entry_yes_ask)::numeric, 4) AS avg_yes_ask,
  ROUND(AVG(entry_no_ask)::numeric, 4) AS avg_no_ask,
  ROUND(AVG(n_snaps_yes)::numeric, 0) AS avg_snaps_per_market
FROM tmp_btc_markets
GROUP BY timeframe;

-- Show a few ambiguous cases so we understand the data
SELECT slug, outcome_up, final_yes_bid, final_yes_ask, final_no_bid, final_no_ask, n_snaps_yes
FROM tmp_btc_markets
WHERE outcome_up IS NULL
ORDER BY timeframe, resolve_unix
LIMIT 6;

-- Export
\copy (SELECT * FROM tmp_btc_markets WHERE outcome_up IS NOT NULL) TO '/tmp/btc_markets.csv' WITH CSV HEADER;
\echo Exported resolved markets to /tmp/btc_markets.csv
