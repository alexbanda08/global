-- Extract per-market trajectory summary for BTC 5m and 15m markets.
-- One row per resolved market with everything needed for backtesting.
--
-- Columns:
--   slug, timeframe, resolve_unix, resolve_at, window_start_unix, window_start_at
--   entry_yes_ask, entry_no_ask      : near window_start (UP buy, DOWN buy)
--   entry_yes_bid, entry_no_bid      : (for sanity / spread check)
--   peak_yes_mid, trough_yes_mid     : during window (for target/stop exits)
--   final_yes_bid, final_no_bid      : last snapshot
--   outcome_up                        : 1 if final yes bid >= 0.9, 0 if <= 0.1, else NULL (ambiguous)
--   n_snaps_in_window                 : sanity
--
-- Write CSV to /tmp/btc_markets.csv for scp-download.

DROP TABLE IF EXISTS tmp_btc_markets;
CREATE TEMP TABLE tmp_btc_markets AS
WITH parsed AS (
  SELECT
    slug,
    CASE WHEN slug LIKE 'btc-updown-5m-%' THEN '5m' ELSE '15m' END AS timeframe,
    CAST(substring(slug FROM '[0-9]+$') AS bigint) AS resolve_unix,
    CASE WHEN slug LIKE 'btc-updown-5m-%' THEN 300 ELSE 900 END AS window_span_s
  FROM orderbook_snapshots_v2
  WHERE slug ~ '^btc-updown-(5|15)m-[0-9]+$'
  GROUP BY slug
),
resolvable AS (
  SELECT slug, timeframe, resolve_unix, window_span_s,
         (resolve_unix - window_span_s) AS window_start_unix
  FROM parsed
  WHERE resolve_unix < extract(epoch FROM NOW())::bigint
),
-- Entry snapshot: closest snapshot >= window_start (first snap in the active window)
entry_snap AS (
  SELECT DISTINCT ON (r.slug, o.outcome)
    r.slug, o.outcome,
    o.timestamp_us,
    o.bid_price_0 AS bid,
    o.ask_price_0 AS ask,
    o.bid_size_0 AS bid_size,
    o.ask_size_0 AS ask_size
  FROM resolvable r
  JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
  WHERE o.timestamp_us/1000000 >= r.window_start_unix
  ORDER BY r.slug, o.outcome, o.timestamp_us ASC
),
-- Last snapshot (for resolution): highest timestamp per slug, per outcome
last_snap AS (
  SELECT DISTINCT ON (r.slug, o.outcome)
    r.slug, o.outcome,
    o.bid_price_0 AS bid,
    o.ask_price_0 AS ask,
    o.timestamp_us
  FROM resolvable r
  JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
  ORDER BY r.slug, o.outcome, o.timestamp_us DESC
),
-- Peak + trough YES mid during window
yes_extrema AS (
  SELECT r.slug,
    MAX((o.bid_price_0 + o.ask_price_0)/2.0) AS peak_yes_mid,
    MIN((o.bid_price_0 + o.ask_price_0)/2.0) AS trough_yes_mid,
    COUNT(*) AS n_snaps_yes
  FROM resolvable r
  JOIN orderbook_snapshots_v2 o ON o.slug = r.slug
  WHERE o.outcome = 'Up'
    AND o.timestamp_us/1000000 >= r.window_start_unix
    AND o.bid_price_0 IS NOT NULL AND o.ask_price_0 IS NOT NULL
  GROUP BY r.slug
)
SELECT
  r.slug, r.timeframe, r.resolve_unix, r.window_start_unix,
  to_timestamp(r.resolve_unix) AS resolve_at,
  to_timestamp(r.window_start_unix) AS window_start_at,
  -- Entry prices at window start
  e_up.bid AS entry_yes_bid, e_up.ask AS entry_yes_ask,
  e_up.bid_size AS entry_yes_bid_size, e_up.ask_size AS entry_yes_ask_size,
  e_dn.bid AS entry_no_bid, e_dn.ask AS entry_no_ask,
  -- Trajectory extrema
  ye.peak_yes_mid, ye.trough_yes_mid, ye.n_snaps_yes,
  -- Final prices
  l_up.bid AS final_yes_bid, l_up.ask AS final_yes_ask,
  l_dn.bid AS final_no_bid,  l_dn.ask AS final_no_ask,
  -- Outcome determination: if final YES bid >=0.9 -> UP won; if <=0.1 -> DOWN won; else NULL
  CASE
    WHEN l_up.bid >= 0.9 THEN 1
    WHEN l_up.bid <= 0.1 THEN 0
    ELSE NULL
  END AS outcome_up
FROM resolvable r
LEFT JOIN entry_snap e_up ON e_up.slug = r.slug AND e_up.outcome = 'Up'
LEFT JOIN entry_snap e_dn ON e_dn.slug = r.slug AND e_dn.outcome = 'Down'
LEFT JOIN last_snap  l_up ON l_up.slug = r.slug AND l_up.outcome = 'Up'
LEFT JOIN last_snap  l_dn ON l_dn.slug = r.slug AND l_dn.outcome = 'Down'
LEFT JOIN yes_extrema ye ON ye.slug = r.slug;

-- Summary stats (what we'll be working with)
SELECT timeframe,
  COUNT(*) AS markets,
  SUM(CASE WHEN outcome_up = 1 THEN 1 ELSE 0 END) AS up_wins,
  SUM(CASE WHEN outcome_up = 0 THEN 1 ELSE 0 END) AS down_wins,
  SUM(CASE WHEN outcome_up IS NULL THEN 1 ELSE 0 END) AS ambiguous,
  ROUND(AVG(entry_yes_ask)::numeric, 4) AS avg_yes_ask,
  ROUND(AVG(entry_no_ask)::numeric, 4) AS avg_no_ask,
  ROUND(AVG(entry_yes_ask - entry_yes_bid)::numeric, 4) AS avg_yes_spread
FROM tmp_btc_markets
GROUP BY timeframe;

-- Export CSV
\copy tmp_btc_markets TO '/tmp/btc_markets.csv' WITH CSV HEADER;

\echo Exported to /tmp/btc_markets.csv
