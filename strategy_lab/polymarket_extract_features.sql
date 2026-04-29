-- Export 1m/5m/15m klines and metrics scoped to the Polymarket market window.
-- 2026-04-21 00:00 UTC → 2026-04-28 00:00 UTC (covers ~7 days, all 1,897 BTC markets).

\copy (SELECT time_period_start_us, symbol_id, period_id, price_open, price_high, price_low, price_close, volume_traded FROM binance_klines_v2 WHERE symbol_id='BINANCE_SPOT_BTC_USDT' AND period_id IN ('1MIN','5MIN','15MIN') AND time_period_start_us BETWEEN 1776729600000000 AND 1777334400000000 ORDER BY period_id, time_period_start_us) TO '/tmp/btc_klines_window.csv' WITH CSV HEADER;

\copy (SELECT create_time_us, symbol, sum_open_interest, sum_open_interest_value, count_long_short_ratio, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, sum_taker_long_short_vol_ratio FROM binance_metrics_v2 WHERE symbol='BTCUSDT' AND create_time_us BETWEEN 1776729600000000 AND 1777334400000000 ORDER BY create_time_us) TO '/tmp/btc_metrics_window.csv' WITH CSV HEADER;

\echo Exported klines and metrics windows.
