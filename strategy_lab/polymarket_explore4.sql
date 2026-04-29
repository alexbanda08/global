-- Parse resolve_unix from slug, count resolvable markets per timeframe+symbol
WITH parsed AS (
  SELECT DISTINCT
    market_id,
    slug,
    CASE
      WHEN slug LIKE 'btc-updown-5m-%'  THEN 'BTC_5m'
      WHEN slug LIKE 'btc-updown-15m-%' THEN 'BTC_15m'
      WHEN slug LIKE 'eth-updown-5m-%'  THEN 'ETH_5m'
      WHEN slug LIKE 'eth-updown-15m-%' THEN 'ETH_15m'
      WHEN slug LIKE 'sol-updown-5m-%'  THEN 'SOL_5m'
      WHEN slug LIKE 'sol-updown-15m-%' THEN 'SOL_15m'
      ELSE NULL END AS bucket,
    CASE
      WHEN slug ~ '^(btc|eth|sol)-updown-(5|15)m-[0-9]+$'
      THEN CAST(substring(slug FROM '[0-9]+$') AS bigint) END AS resolve_unix
  FROM orderbook_snapshots_v2
)
SELECT bucket,
       COUNT(*) AS markets,
       SUM(CASE WHEN resolve_unix < extract(epoch FROM NOW())::bigint THEN 1 ELSE 0 END) AS past,
       SUM(CASE WHEN resolve_unix >= extract(epoch FROM NOW())::bigint THEN 1 ELSE 0 END) AS future,
       to_timestamp(MIN(resolve_unix)) AS earliest_resolve,
       to_timestamp(MAX(resolve_unix)) AS latest_resolve
FROM parsed
WHERE bucket IS NOT NULL
GROUP BY bucket
ORDER BY bucket;

-- Binance BTC kline schema + date range
\d binance_klines_v2

SELECT exchange, symbol, interval, COUNT(*) AS klines,
       to_timestamp(MIN(open_time_us)/1000000) AS earliest,
       to_timestamp(MAX(open_time_us)/1000000) AS latest
FROM binance_klines_v2
WHERE symbol IN ('BTCUSDT', 'ETHUSDT', 'SOLUSDT') AND interval IN ('5m', '15m', '1m')
GROUP BY exchange, symbol, interval
ORDER BY symbol, interval;
