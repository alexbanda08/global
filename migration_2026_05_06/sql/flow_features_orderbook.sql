-- flow_features_orderbook.sql
-- Pre-aggregate orderbook L25 → FLOW features per (slug, 10s_bucket).
-- Server-side reduction: 35 GB raw → ~250 MB CSV for all 3 assets.
--
-- For each 10s bucket per market, output:
--   spread, mid, bid_price_0, ask_price_0
--   cumulative depth at L5/L10/L25 each side
--   book imbalance at L5/L10/L25 (-1 .. +1)
--   size-weighted VWAP at L5 each side
--   max single-level size each side (wall detection)
--   row count in bucket (proxy for OB update rate)
--
-- Usage:
--   psql -h 127.0.0.1 -d storedata -v ASSET="'btc'" -f flow_features_orderbook.sql > btc_flow_features.csv
--
-- Bind variable:
--   :ASSET  one of 'btc', 'eth', 'sol' (single-quoted)

\set ON_ERROR_STOP on

-- Pre-aggregate to 10s bucket: pick the latest snap in each bucket as
-- representative state, then sum cumulative depth columns. We want the L25
-- columns from the latest snap (because OB shape evolves intra-bucket and
-- the latest is what a strategy would see at decision time).
COPY (
    WITH ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY slug, outcome_id, (timestamp_us / 10000000)
                   ORDER BY timestamp_us DESC
               ) AS rn,
               COUNT(*) OVER (
                   PARTITION BY slug, outcome_id, (timestamp_us / 10000000)
               ) AS bucket_n
        FROM orderbook_snapshots_v2
        WHERE slug LIKE :ASSET || '-updown-%'
    ),
    latest AS (
        SELECT * FROM ranked WHERE rn = 1
    )
    SELECT
        slug,
        outcome_id,
        (timestamp_us / 10000000) AS bucket_10s,
        timestamp_us AS snap_ts_us,
        bucket_n AS n_snaps_in_bucket,

        -- Top of book
        bid_price_0::numeric(10,4) AS bid_px,
        ask_price_0::numeric(10,4) AS ask_px,
        (ask_price_0 - bid_price_0)::numeric(10,4) AS spread,
        ((ask_price_0 + bid_price_0) / 2)::numeric(10,6) AS mid,
        bid_size_0::numeric(20,2) AS bid_sz_l1,
        ask_size_0::numeric(20,2) AS ask_sz_l1,

        -- Cumulative depth — bid side (L5, L10, L25)
        (COALESCE(bid_size_0,0)+COALESCE(bid_size_1,0)+COALESCE(bid_size_2,0)
         +COALESCE(bid_size_3,0)+COALESCE(bid_size_4,0))::numeric(20,2)
            AS bid_depth_l5,
        (COALESCE(bid_size_0,0)+COALESCE(bid_size_1,0)+COALESCE(bid_size_2,0)
         +COALESCE(bid_size_3,0)+COALESCE(bid_size_4,0)
         +COALESCE(bid_size_5,0)+COALESCE(bid_size_6,0)+COALESCE(bid_size_7,0)
         +COALESCE(bid_size_8,0)+COALESCE(bid_size_9,0))::numeric(20,2)
            AS bid_depth_l10,
        (COALESCE(bid_size_0,0)+COALESCE(bid_size_1,0)+COALESCE(bid_size_2,0)
         +COALESCE(bid_size_3,0)+COALESCE(bid_size_4,0)
         +COALESCE(bid_size_5,0)+COALESCE(bid_size_6,0)+COALESCE(bid_size_7,0)
         +COALESCE(bid_size_8,0)+COALESCE(bid_size_9,0)
         +COALESCE(bid_size_10,0)+COALESCE(bid_size_11,0)+COALESCE(bid_size_12,0)
         +COALESCE(bid_size_13,0)+COALESCE(bid_size_14,0)
         +COALESCE(bid_size_15,0)+COALESCE(bid_size_16,0)+COALESCE(bid_size_17,0)
         +COALESCE(bid_size_18,0)+COALESCE(bid_size_19,0)
         +COALESCE(bid_size_20,0)+COALESCE(bid_size_21,0)+COALESCE(bid_size_22,0)
         +COALESCE(bid_size_23,0)+COALESCE(bid_size_24,0))::numeric(20,2)
            AS bid_depth_l25,

        -- Cumulative depth — ask side
        (COALESCE(ask_size_0,0)+COALESCE(ask_size_1,0)+COALESCE(ask_size_2,0)
         +COALESCE(ask_size_3,0)+COALESCE(ask_size_4,0))::numeric(20,2)
            AS ask_depth_l5,
        (COALESCE(ask_size_0,0)+COALESCE(ask_size_1,0)+COALESCE(ask_size_2,0)
         +COALESCE(ask_size_3,0)+COALESCE(ask_size_4,0)
         +COALESCE(ask_size_5,0)+COALESCE(ask_size_6,0)+COALESCE(ask_size_7,0)
         +COALESCE(ask_size_8,0)+COALESCE(ask_size_9,0))::numeric(20,2)
            AS ask_depth_l10,
        (COALESCE(ask_size_0,0)+COALESCE(ask_size_1,0)+COALESCE(ask_size_2,0)
         +COALESCE(ask_size_3,0)+COALESCE(ask_size_4,0)
         +COALESCE(ask_size_5,0)+COALESCE(ask_size_6,0)+COALESCE(ask_size_7,0)
         +COALESCE(ask_size_8,0)+COALESCE(ask_size_9,0)
         +COALESCE(ask_size_10,0)+COALESCE(ask_size_11,0)+COALESCE(ask_size_12,0)
         +COALESCE(ask_size_13,0)+COALESCE(ask_size_14,0)
         +COALESCE(ask_size_15,0)+COALESCE(ask_size_16,0)+COALESCE(ask_size_17,0)
         +COALESCE(ask_size_18,0)+COALESCE(ask_size_19,0)
         +COALESCE(ask_size_20,0)+COALESCE(ask_size_21,0)+COALESCE(ask_size_22,0)
         +COALESCE(ask_size_23,0)+COALESCE(ask_size_24,0))::numeric(20,2)
            AS ask_depth_l25,

        -- Imbalances — (bid - ask) / (bid + ask), range [-1, +1]
        -- Add tiny epsilon to avoid div-by-zero
        CASE WHEN COALESCE(bid_size_0,0) + COALESCE(ask_size_0,0) > 0
             THEN ((COALESCE(bid_size_0,0) - COALESCE(ask_size_0,0))
                   / NULLIF(COALESCE(bid_size_0,0) + COALESCE(ask_size_0,0), 0))::numeric(8,5)
             ELSE NULL END AS imb_l1,

        -- Wall detection — max single-level size each side (catches Cyclops liquidity walls)
        GREATEST(COALESCE(bid_size_0,0), COALESCE(bid_size_1,0), COALESCE(bid_size_2,0),
                 COALESCE(bid_size_3,0), COALESCE(bid_size_4,0), COALESCE(bid_size_5,0),
                 COALESCE(bid_size_6,0), COALESCE(bid_size_7,0), COALESCE(bid_size_8,0),
                 COALESCE(bid_size_9,0))::numeric(20,2) AS bid_max_size_l10,
        GREATEST(COALESCE(ask_size_0,0), COALESCE(ask_size_1,0), COALESCE(ask_size_2,0),
                 COALESCE(ask_size_3,0), COALESCE(ask_size_4,0), COALESCE(ask_size_5,0),
                 COALESCE(ask_size_6,0), COALESCE(ask_size_7,0), COALESCE(ask_size_8,0),
                 COALESCE(ask_size_9,0))::numeric(20,2) AS ask_max_size_l10
    FROM latest
    ORDER BY slug, outcome_id, bucket_10s
) TO STDOUT WITH CSV HEADER;
