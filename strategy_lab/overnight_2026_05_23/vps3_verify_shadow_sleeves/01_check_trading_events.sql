-- VPS3 trading.events check for the 9 new shadow sleeves.
-- Run as `psql storedata -f 01_check_trading_events.sql` on VPS3.

-- ============================================================
-- 1) Have any of the 9 new sleeves emitted events in the last 7 days?
-- ============================================================
\echo '=== presence check: which of the 9 specced sleeves are firing? ==='
SELECT
  sleeve_id,
  COUNT(*) AS events_7d,
  MIN(at)  AS first_seen,
  MAX(at)  AS last_seen,
  COUNT(*) FILTER (WHERE kind = 'poly_updown_signal_shadow') AS signals_shadow,
  COUNT(*) FILTER (WHERE kind = 'poly_updown_signal')        AS signals_live,
  COUNT(*) FILTER (WHERE kind = 'poly_updown_resolution')    AS resolutions
FROM trading.events
WHERE at >= NOW() - INTERVAL '7 days'
  AND sleeve_id IN (
    'shadow_poly_updown_ALL_5m_phase1_kelly',
    'shadow_poly_updown_btc_5m_fade_momo_v2',
    'shadow_poly_updown_btc_5m_fade_sniper',
    'shadow_poly_updown_eth_15m_fade_sniper',
    'shadow_poly_updown_sol_5m_fade_sniper',
    'shadow_poly_updown_sol_5m_fade_momo_v2',
    'shadow_poly_updown_sol_15m_fade_momo_v2',
    'shadow_poly_updown_ALL_5m_S3_prewindow',
    'shadow_poly_updown_ALL_15m_S4_prewindow'
  )
GROUP BY sleeve_id
ORDER BY events_7d DESC;

-- ============================================================
-- 2) Catch-all: any sleeve_id starting with "shadow_" since the spec was written
-- ============================================================
\echo '=== anything new under shadow_* prefix (last 2 days) ==='
SELECT
  sleeve_id,
  COUNT(*) AS events,
  MIN(at) AS first_seen,
  MAX(at) AS last_seen
FROM trading.events
WHERE at >= NOW() - INTERVAL '2 days'
  AND sleeve_id LIKE 'shadow_%'
GROUP BY sleeve_id
ORDER BY first_seen;

-- ============================================================
-- 3) Per-sleeve fire rate vs backtest expectation (last 24h)
-- ============================================================
\echo '=== fires per sleeve in last 24h (compare against expected) ==='
WITH expected AS (
  SELECT * FROM (VALUES
    ('shadow_poly_updown_ALL_5m_phase1_kelly',      167::int),
    ('shadow_poly_updown_btc_5m_fade_momo_v2',       35::int),
    ('shadow_poly_updown_btc_5m_fade_sniper',        30::int),
    ('shadow_poly_updown_eth_15m_fade_sniper',       15::int),
    ('shadow_poly_updown_sol_5m_fade_sniper',        17::int),
    ('shadow_poly_updown_sol_5m_fade_momo_v2',       17::int),
    ('shadow_poly_updown_sol_15m_fade_momo_v2',       4::int),
    ('shadow_poly_updown_ALL_5m_S3_prewindow',       95::int),
    ('shadow_poly_updown_ALL_15m_S4_prewindow',      11::int)
  ) AS t(sleeve_id, expected_fires_per_day)
)
SELECT
  e.sleeve_id,
  e.expected_fires_per_day                                       AS expected,
  COALESCE(c.live_fires, 0)                                      AS observed_24h,
  ROUND(100.0 * COALESCE(c.live_fires, 0) / e.expected_fires_per_day, 1)
                                                                 AS pct_of_expected,
  CASE WHEN COALESCE(c.live_fires, 0) = 0 THEN 'NOT DEPLOYED OR DEAD'
       WHEN c.live_fires < 0.5 * e.expected_fires_per_day        THEN 'LOW (<50%)'
       WHEN c.live_fires > 2   * e.expected_fires_per_day        THEN 'HIGH (>200%)'
       ELSE 'OK'
  END                                                            AS verdict
FROM expected e
LEFT JOIN (
  SELECT sleeve_id, COUNT(*) AS live_fires
  FROM trading.events
  WHERE at >= NOW() - INTERVAL '24 hours'
    AND kind IN ('poly_updown_signal', 'poly_updown_signal_shadow')
  GROUP BY sleeve_id
) c USING (sleeve_id)
ORDER BY e.expected_fires_per_day DESC;

-- ============================================================
-- 4) Realized PnL per shadow sleeve (matched fires → resolutions)
-- ============================================================
\echo '=== realized PnL per shadow sleeve (last 7d, $25 base, before Kelly) ==='
WITH fires AS (
  SELECT
    e.event_id AS fire_id, e.sleeve_id, e.at AS fire_at,
    (e.data->>'slug')               AS slug,
    (e.data->>'signal')             AS direction,
    (e.data->>'vwap')::float        AS entry_vwap,
    (e.data->>'shares')::float      AS shares,
    (e.data->>'usd')::float         AS notional_usd
  FROM trading.events e
  WHERE e.at >= NOW() - INTERVAL '7 days'
    AND e.kind IN ('poly_updown_signal', 'poly_updown_signal_shadow')
    AND e.sleeve_id LIKE 'shadow_%'
), resols AS (
  SELECT
    (data->>'slug')                AS slug,
    (data->>'outcome')             AS outcome,
    sleeve_id,
    (data->>'pnl_usd')::float      AS pnl_usd
  FROM trading.events
  WHERE at >= NOW() - INTERVAL '8 days'
    AND kind = 'poly_updown_resolution'
), joined AS (
  SELECT f.sleeve_id, f.entry_vwap, f.notional_usd,
         r.outcome, r.pnl_usd,
         (CASE WHEN UPPER(f.direction) = 'UP'   AND r.outcome = 'Up'
                 OR UPPER(f.direction) = 'DOWN' AND r.outcome = 'Down'
               THEN 1 ELSE 0 END) AS won
  FROM fires f
  LEFT JOIN resols r ON r.slug = f.slug AND r.sleeve_id = f.sleeve_id
)
SELECT
  sleeve_id,
  COUNT(*)                                              AS n,
  ROUND(100.0 * AVG(won)::numeric, 2)                   AS wr_pct,
  ROUND(SUM(pnl_usd)::numeric, 2)                       AS sum_pnl_usd,
  ROUND(AVG(pnl_usd)::numeric, 3)                       AS per_trade,
  ROUND(AVG(notional_usd)::numeric, 2)                  AS avg_notional,
  ROUND(AVG(entry_vwap)::numeric, 3)                    AS avg_entry_vwap
FROM joined
GROUP BY sleeve_id
ORDER BY sum_pnl_usd DESC;

-- ============================================================
-- 5) Feature-payload sanity check (last 100 fires per shadow sleeve)
-- ============================================================
\echo '=== feature payload sanity: how many fires carry each required new feature? ==='
SELECT
  sleeve_id,
  COUNT(*) AS total_fires,
  COUNT(*) FILTER (WHERE data ? 'fair_edge_bp')   AS has_fair_edge,
  COUNT(*) FILTER (WHERE data ? 'fair_up')        AS has_fair_up,
  COUNT(*) FILTER (WHERE data ? 'cvd_30s')        AS has_cvd_30s,
  COUNT(*) FILTER (WHERE data ? 'macd_hist')      AS has_macd_hist,
  COUNT(*) FILTER (WHERE data ? 'rvol_30_300')    AS has_rvol,
  COUNT(*) FILTER (WHERE data ? 'imb5')           AS has_imb5,
  COUNT(*) FILTER (WHERE data ? 'kelly_mult')     AS has_kelly_mult,
  COUNT(*) FILTER (WHERE data ? 'fire_offset_s')  AS has_offset
FROM trading.events
WHERE at >= NOW() - INTERVAL '48 hours'
  AND kind IN ('poly_updown_signal', 'poly_updown_signal_shadow')
  AND sleeve_id LIKE 'shadow_%'
GROUP BY sleeve_id;

-- ============================================================
-- 6) Kelly tier distribution on the phase1 sleeve
-- ============================================================
\echo '=== Kelly tier distribution on phase1 ensemble (sanity) ==='
SELECT
  (data->>'kelly_mult')::float AS kelly_mult,
  COUNT(*)                     AS fires,
  ROUND(AVG((data->>'fair_edge_bp')::float)::numeric, 1) AS avg_fair_edge,
  ROUND(AVG((data->>'usd')::float)::numeric, 2)          AS avg_notional
FROM trading.events
WHERE at >= NOW() - INTERVAL '7 days'
  AND sleeve_id = 'shadow_poly_updown_ALL_5m_phase1_kelly'
  AND kind IN ('poly_updown_signal', 'poly_updown_signal_shadow')
GROUP BY 1
ORDER BY 1;

-- ============================================================
-- 7) FADE companion hook check — does shadow fire OPPOSITE of production?
-- ============================================================
\echo '=== FADE-UNGATED sanity: shadow direction should be OPPOSITE of prod ==='
WITH prod AS (
  SELECT
    (data->>'slug')   AS slug,
    (data->>'signal') AS prod_dir,
    sleeve_id
  FROM trading.events
  WHERE at >= NOW() - INTERVAL '48 hours'
    AND kind = 'poly_updown_signal'
    AND sleeve_id IN (
      'poly_updown_btc_5m_momo_v2_HOLD', 'poly_updown_btc_5m_sniper',
      'poly_updown_eth_15m_sniper', 'poly_updown_sol_5m_sniper',
      'poly_updown_sol_5m_momo_v2_HOLD', 'poly_updown_sol_15m_momo_v2_HOLD'
    )
), fade AS (
  SELECT
    (data->>'slug')   AS slug,
    (data->>'signal') AS fade_dir,
    sleeve_id
  FROM trading.events
  WHERE at >= NOW() - INTERVAL '48 hours'
    AND kind IN ('poly_updown_signal', 'poly_updown_signal_shadow')
    AND sleeve_id LIKE 'shadow_poly_updown_%_fade_%'
)
SELECT
  p.sleeve_id AS prod_sleeve, p.prod_dir,
  f.sleeve_id AS fade_sleeve, f.fade_dir,
  CASE WHEN UPPER(p.prod_dir) = UPPER(f.fade_dir) THEN 'BUG: SAME DIRECTION'
       WHEN (UPPER(p.prod_dir) = 'UP' AND UPPER(f.fade_dir) = 'DOWN')
         OR (UPPER(p.prod_dir) = 'DOWN' AND UPPER(f.fade_dir) = 'UP')
       THEN 'OK: OPPOSITE'
       ELSE 'UNKNOWN' END AS check
FROM prod p
JOIN fade f USING (slug)
LIMIT 20;

-- ============================================================
-- 8) Pre-window fire offset check
-- ============================================================
\echo '=== Pre-window timing check: S3 5m should fire 60s BEFORE slot_start ==='
SELECT
  (data->>'fire_offset_s')::int  AS fire_offset_s,
  COUNT(*) AS fires
FROM trading.events
WHERE at >= NOW() - INTERVAL '7 days'
  AND sleeve_id IN (
    'shadow_poly_updown_ALL_5m_S3_prewindow',
    'shadow_poly_updown_ALL_15m_S4_prewindow'
  )
  AND kind IN ('poly_updown_signal', 'poly_updown_signal_shadow')
GROUP BY 1, sleeve_id;
