-- Resolved-status detail: how many have outcome/result populated
SELECT timeframe,
       SUM(CASE WHEN resolve_at < NOW() THEN 1 ELSE 0 END) AS past_resolve_at,
       SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS has_outcome,
       SUM(CASE WHEN result IS NOT NULL THEN 1 ELSE 0 END) AS has_result,
       SUM(CASE WHEN resolved_at IS NOT NULL THEN 1 ELSE 0 END) AS has_resolved_at,
       COUNT(*) AS total
FROM markets WHERE platform = 'polymarket'
GROUP BY timeframe;

-- Sample BTC 5m market rows
SELECT timeframe, LEFT(title, 55) AS title, resolve_at, resolved_at, outcome, result, yes_bid, yes_ask, volume
FROM markets
WHERE (title ILIKE '%btc%' OR title ILIKE '%bitcoin%')
ORDER BY resolve_at DESC LIMIT 4;

-- Orderbook time range + snapshot frequency for BTC 5m markets
SELECT to_timestamp(MIN(timestamp_us)/1000000) AS earliest,
       to_timestamp(MAX(timestamp_us)/1000000) AS latest,
       COUNT(*) AS total_snaps,
       COUNT(DISTINCT market_id) AS distinct_markets
FROM orderbook_snapshots_v2;

-- Example snapshot for one BTC 5m market: how tight is the book?
SELECT to_timestamp(timestamp_us/1000000) AS ts, outcome, bid_price_0, bid_size_0, ask_price_0, ask_size_0
FROM orderbook_snapshots_v2
WHERE market_id IN (SELECT market_id FROM markets WHERE timeframe='5m' AND (title ILIKE '%btc%' OR title ILIKE '%bitcoin%') LIMIT 1)
ORDER BY timestamp_us DESC LIMIT 6;
