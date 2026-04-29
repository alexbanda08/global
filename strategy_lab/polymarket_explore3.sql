-- 1. What slugs look like in the snapshot table (sample from distinct markets)
SELECT DISTINCT slug FROM orderbook_snapshots_v2 LIMIT 20;

-- 2. Count BTC/ETH/SOL markets by slug pattern
SELECT
  SUM(CASE WHEN slug ILIKE '%bitcoin%' OR slug ILIKE '%btc%' THEN 1 ELSE 0 END) AS btc,
  SUM(CASE WHEN slug ILIKE '%ethereum%' OR slug ILIKE '%eth%' THEN 1 ELSE 0 END) AS eth,
  SUM(CASE WHEN slug ILIKE '%solana%' OR slug ILIKE '%sol%' THEN 1 ELSE 0 END) AS sol,
  COUNT(DISTINCT market_id) AS total
FROM orderbook_snapshots_v2;

-- 3. BTC-specific slugs + timeframe pattern (looking for '5-min' / '15-min' / hourly etc)
SELECT slug, COUNT(*) AS snaps
FROM orderbook_snapshots_v2
WHERE slug ILIKE '%bitcoin%' OR slug ILIKE '%btc%'
GROUP BY slug
ORDER BY snaps DESC
LIMIT 15;

-- 4. Per-market snapshot density (how granular is the data)
SELECT slug,
       COUNT(*) AS snaps,
       (MAX(timestamp_us) - MIN(timestamp_us))/1000000.0 AS span_sec,
       ROUND(COUNT(*)::numeric / NULLIF((MAX(timestamp_us) - MIN(timestamp_us))/1000000.0, 0), 2) AS snaps_per_sec
FROM orderbook_snapshots_v2
WHERE slug ILIKE '%bitcoin%'
GROUP BY slug
ORDER BY snaps DESC
LIMIT 5;
