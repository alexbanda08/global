-- flow_features_trades.sql
-- Pre-aggregate trades_v2 → CVD/aggressor features per (slug, 10s_bucket).
-- 38 GB raw → ~80 MB CSV for all 3 assets.
--
-- For each 10s bucket per market+outcome, output:
--   n_trades, sum_size, avg_price, vwap
--   buy_size, sell_size (by `side` field — Polymarket uses 'buy'/'sell' on the YES token)
--   cvd_delta = buy_size - sell_size  (cumulative volume delta increment)
--   aggressor_ratio = buy_size / (buy_size + sell_size)
--
-- Usage:
--   psql -h 127.0.0.1 -d storedata -v ASSET="'btc'" -f flow_features_trades.sql > btc_trade_features.csv

\set ON_ERROR_STOP on

COPY (
    SELECT
        slug,
        outcome,
        outcome_id,
        (timestamp_us / 10000000) AS bucket_10s,
        MIN(timestamp_us) AS bucket_start_us,
        MAX(timestamp_us) AS bucket_end_us,
        COUNT(*) AS n_trades,
        SUM(size)::numeric(20,2) AS sum_size,
        AVG(price)::numeric(10,5) AS avg_price,
        (SUM(size * price) / NULLIF(SUM(size), 0))::numeric(10,5) AS vwap,
        SUM(CASE WHEN side = 'buy'  THEN size ELSE 0 END)::numeric(20,2) AS buy_size,
        SUM(CASE WHEN side = 'sell' THEN size ELSE 0 END)::numeric(20,2) AS sell_size,
        (SUM(CASE WHEN side = 'buy'  THEN size ELSE 0 END)
         - SUM(CASE WHEN side = 'sell' THEN size ELSE 0 END))::numeric(20,2)
            AS cvd_delta,
        CASE WHEN SUM(size) > 0
             THEN (SUM(CASE WHEN side = 'buy' THEN size ELSE 0 END) / SUM(size))::numeric(8,5)
             ELSE NULL END AS aggressor_ratio,
        MIN(price)::numeric(10,5) AS min_price,
        MAX(price)::numeric(10,5) AS max_price
    FROM trades_v2
    WHERE slug LIKE :ASSET || '-updown-%'
    GROUP BY slug, outcome, outcome_id, bucket_10s
    ORDER BY slug, outcome_id, bucket_10s
) TO STDOUT WITH CSV HEADER;
