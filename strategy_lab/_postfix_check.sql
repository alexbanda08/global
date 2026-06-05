\echo === vwap + fairedge + m5v placements since restart 09:50 UTC ===
SELECT sleeve_id, count(*) n_resolution, max(at) last_fire
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND at > timestamp '2026-06-01 09:50'
  AND (sleeve_id LIKE '%vwap_off%' OR sleeve_id LIKE '%fairedge%' OR sleeve_id LIKE '%_m5v%' OR sleeve_id LIKE '%cvd_macd%' OR sleeve_id LIKE '%momo_v1_m5v%')
GROUP BY 1 ORDER BY 1;

\echo === any signal events (did they evaluate post-restart) ===
SELECT sleeve_id, count(*) n_signal
FROM trading.events
WHERE kind='poly_updown_signal'
  AND at > timestamp '2026-06-01 09:50'
  AND (sleeve_id LIKE '%vwap_off%' OR sleeve_id LIKE '%fairedge%' OR sleeve_id LIKE '%_m5v%' OR sleeve_id LIKE '%cvd_macd%')
GROUP BY 1 ORDER BY 1;

\echo === liq tables row counts + max ts ===
SELECT 'bybit' v, count(*), max(time_exchange_us) FROM bybit_liquidations_v2
UNION ALL SELECT 'bitget', count(*), max(time_exchange_us) FROM bitget_liquidations_v2
UNION ALL SELECT 'okx', count(*), max(time_exchange_us) FROM okx_liquidations_v2
UNION ALL SELECT 'gate', count(*), max(time_exchange_us) FROM gate_liquidations_v2;
