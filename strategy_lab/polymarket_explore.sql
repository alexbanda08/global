-- Symbol breakdown per timeframe
SELECT timeframe,
       COUNT(*) FILTER (WHERE title ILIKE '%btc%' OR title ILIKE '%bitcoin%') AS btc,
       COUNT(*) FILTER (WHERE title ILIKE '%eth%' OR title ILIKE '%ethereum%') AS eth,
       COUNT(*) FILTER (WHERE title ILIKE '%sol%' OR title ILIKE '%solana%') AS sol,
       COUNT(*) AS total,
       SUM(CASE WHEN resolved_at IS NOT NULL THEN 1 ELSE 0 END) AS resolved
FROM markets WHERE platform = 'polymarket'
GROUP BY timeframe;

-- Orderbook snapshot volume
SELECT COUNT(*) AS snapshots FROM orderbook_snapshots_v2;
\d orderbook_snapshots_v2

-- Sample BTC 5m markets (most recent)
SELECT market_id, LEFT(title, 60) AS title, resolve_at, resolved_at, outcome, result, yes_bid, yes_ask, volume
FROM markets
WHERE timeframe = '5m' AND (title ILIKE '%btc%' OR title ILIKE '%bitcoin%')
ORDER BY resolve_at DESC LIMIT 5;

-- Sample BTC 15m markets
SELECT market_id, LEFT(title, 60) AS title, resolve_at, resolved_at, outcome, result, yes_bid, yes_ask, volume
FROM markets
WHERE timeframe = '15m' AND (title ILIKE '%btc%' OR title ILIKE '%bitcoin%')
ORDER BY resolve_at DESC LIMIT 3;
