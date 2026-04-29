-- polymarket_extract_flow.sql
-- Extract per-market 60s pre-window trade flow for resolved UpDown markets.
-- Aggregates trades in [slot_start_us - 60_000_000, slot_start_us] by (slug, outcome, side).
--
-- trades_v2 already carries outcome (Up/Down) and side (buy/sell) per row —
-- no join to markets table needed; join directly via slug.
--
-- Asset-template: replace 'btc-updown-%' and 'btc_flow_v3.csv' via sed for eth/sol.
-- Safety: slug-scoped via market_resolutions_v2 → no full table scan.

\set ASSET_PREFIX 'btc-updown-%'

DROP TABLE IF EXISTS tmp_flow;

CREATE TEMP TABLE tmp_flow AS
WITH resolved AS (
  SELECT
    slug,
    slot_start_us
  FROM market_resolutions_v2
  WHERE slug LIKE :'ASSET_PREFIX'
    AND outcome IS NOT NULL
)
SELECT
  r.slug,
  t.outcome,
  t.side              AS taker_side,
  COUNT(*)            AS n_trades,
  SUM(t.size)         AS total_size
FROM resolved r
JOIN trades_v2 t
  ON t.slug = r.slug
 AND t.timestamp_us BETWEEN r.slot_start_us - 60000000 AND r.slot_start_us
GROUP BY r.slug, t.outcome, t.side;

\copy tmp_flow TO '/tmp/extract/btc_flow_v3.csv' WITH CSV HEADER;
\echo Exported btc_flow_v3.
