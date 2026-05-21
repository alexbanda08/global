-- pull_tier1_full_stdout.sql — server-side L25 entry walk at t+120s
-- Identical join logic to ../data/v4/refresh_2026_05_06/tier1_entries/pull_tier1_full.sql
-- but emits CSV to STDOUT (so caller can stream over SSH) instead of \copy to /tmp.
-- Expects /tmp/universe_lookup_full.csv preloaded with cols: asset,slug,outcome,target_ts_us

\set ON_ERROR_STOP on

DROP TABLE IF EXISTS tmp_universe;
CREATE TEMP TABLE tmp_universe (
    asset TEXT, slug TEXT, outcome TEXT, target_ts_us BIGINT
);
\copy tmp_universe(asset, slug, outcome, target_ts_us) FROM '/tmp/universe_lookup_full.csv' CSV HEADER
CREATE INDEX tmp_uni_slug ON tmp_universe(slug, outcome);

COPY (
  WITH candidates AS (
    SELECT u.asset, u.slug, u.outcome, u.target_ts_us, o.timestamp_us,
           ABS(o.timestamp_us - u.target_ts_us) AS dt_abs,
           o.bid_price_0,  o.bid_size_0,  o.bid_price_1,  o.bid_size_1,
           o.bid_price_2,  o.bid_size_2,  o.bid_price_3,  o.bid_size_3,
           o.bid_price_4,  o.bid_size_4,  o.bid_price_5,  o.bid_size_5,
           o.bid_price_6,  o.bid_size_6,  o.bid_price_7,  o.bid_size_7,
           o.bid_price_8,  o.bid_size_8,  o.bid_price_9,  o.bid_size_9,
           o.bid_price_10, o.bid_size_10, o.bid_price_11, o.bid_size_11,
           o.bid_price_12, o.bid_size_12, o.bid_price_13, o.bid_size_13,
           o.bid_price_14, o.bid_size_14, o.bid_price_15, o.bid_size_15,
           o.bid_price_16, o.bid_size_16, o.bid_price_17, o.bid_size_17,
           o.bid_price_18, o.bid_size_18, o.bid_price_19, o.bid_size_19,
           o.bid_price_20, o.bid_size_20, o.bid_price_21, o.bid_size_21,
           o.bid_price_22, o.bid_size_22, o.bid_price_23, o.bid_size_23,
           o.bid_price_24, o.bid_size_24,
           o.ask_price_0,  o.ask_size_0,  o.ask_price_1,  o.ask_size_1,
           o.ask_price_2,  o.ask_size_2,  o.ask_price_3,  o.ask_size_3,
           o.ask_price_4,  o.ask_size_4,  o.ask_price_5,  o.ask_size_5,
           o.ask_price_6,  o.ask_size_6,  o.ask_price_7,  o.ask_size_7,
           o.ask_price_8,  o.ask_size_8,  o.ask_price_9,  o.ask_size_9,
           o.ask_price_10, o.ask_size_10, o.ask_price_11, o.ask_size_11,
           o.ask_price_12, o.ask_size_12, o.ask_price_13, o.ask_size_13,
           o.ask_price_14, o.ask_size_14, o.ask_price_15, o.ask_size_15,
           o.ask_price_16, o.ask_size_16, o.ask_price_17, o.ask_size_17,
           o.ask_price_18, o.ask_size_18, o.ask_price_19, o.ask_size_19,
           o.ask_price_20, o.ask_size_20, o.ask_price_21, o.ask_size_21,
           o.ask_price_22, o.ask_size_22, o.ask_price_23, o.ask_size_23,
           o.ask_price_24, o.ask_size_24
    FROM tmp_universe u
    JOIN orderbook_snapshots_v2 o
      ON o.slug = u.slug AND o.outcome = u.outcome
     AND o.timestamp_us BETWEEN (u.target_ts_us - 5000000) AND (u.target_ts_us + 5000000)
  ),
  ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY slug, outcome ORDER BY dt_abs ASC) AS rn
    FROM candidates
  )
  SELECT * FROM ranked WHERE rn = 1
) TO STDOUT WITH CSV HEADER;
