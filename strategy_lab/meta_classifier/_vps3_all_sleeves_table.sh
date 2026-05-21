#!/bin/bash
# Per-sleeve stats across ALL poly_updown sleeves (not just momo).
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

OUT=/tmp/all_sleeve_stats.csv

cat > /tmp/all_sleeve_q.sql <<'SQL'
WITH base AS (
  SELECT sleeve_id, kind, at, data
  FROM trading.events
  WHERE at > now() - interval '14 days'
    AND sleeve_id LIKE 'poly_updown_%'
),
signals AS (
  SELECT
    sleeve_id,
    count(*) AS signals_total,
    count(*) FILTER (WHERE data->>'signal' IN ('UP','DOWN')) AS signals_fired,
    count(*) FILTER (WHERE data->>'signal' = 'NONE') AS signals_skipped,
    min(at) AS first_signal_at,
    max(at) AS last_signal_at
  FROM base WHERE kind = 'poly_updown_signal'
  GROUP BY sleeve_id
),
resolutions AS (
  SELECT
    sleeve_id,
    count(*) AS resolved,
    count(*) FILTER (WHERE (data->>'won')::boolean) AS wins,
    count(*) FILTER (WHERE NOT (data->>'won')::boolean) AS losses,
    count(*) FILTER (WHERE (data->>'hedged')::boolean) AS hedged_fired,
    count(*) FILTER (WHERE (data->>'exited_at_bid')::boolean) AS sell_fired,
    count(*) FILTER (WHERE (data->>'partial_bid_exit')::boolean) AS partial_sell_fired,
    round(sum((data->>'pnl_usd')::numeric)::numeric, 2) AS pnl_total_usd,
    round(avg((data->>'pnl_usd')::numeric)::numeric, 4) AS pnl_per_trade_usd,
    round(avg((data->>'entry_price')::numeric)::numeric, 4) AS avg_entry_price,
    round(avg((data->>'entry_qty')::numeric)::numeric, 2) AS avg_entry_qty
  FROM base WHERE kind = 'poly_updown_resolution'
  GROUP BY sleeve_id
),
hedge_skips AS (
  SELECT sleeve_id, count(*) AS hedge_skip_total
  FROM base WHERE kind = 'poly_updown_hedge_skip'
  GROUP BY sleeve_id
),
all_sleeves AS (
  SELECT sleeve_id FROM signals
  UNION SELECT sleeve_id FROM resolutions
  UNION SELECT sleeve_id FROM hedge_skips
)
SELECT
  a.sleeve_id,
  split_part(a.sleeve_id, '_', 3) AS asset,
  split_part(a.sleeve_id, '_', 4) AS tf,
  -- family: anything after asset_tf_, with momo_v2 collapsed
  CASE
    WHEN a.sleeve_id LIKE '%_momo_v2_%' THEN 'momo_v2'
    WHEN a.sleeve_id LIKE '%_momo_%'    THEN 'momo_v1'
    ELSE substring(a.sleeve_id from '^poly_updown_[a-z]+_[0-9]+m_(.*)$')
  END AS family,
  s.first_signal_at, s.last_signal_at,
  round(EXTRACT(EPOCH FROM (s.last_signal_at - s.first_signal_at)) / 3600.0, 2) AS hours_running,
  COALESCE(s.signals_total, 0) AS signals_total,
  COALESCE(s.signals_fired, 0) AS signals_fired,
  COALESCE(s.signals_skipped, 0) AS signals_skipped,
  round(COALESCE(s.signals_fired,0)::numeric * 100 / NULLIF(s.signals_total,0), 2) AS fire_rate_pct,
  COALESCE(r.resolved, 0) AS resolved,
  COALESCE(r.wins, 0) AS wins,
  COALESCE(r.losses, 0) AS losses,
  round(COALESCE(r.wins,0)::numeric * 100 / NULLIF(r.resolved,0), 2) AS win_rate_pct,
  COALESCE(r.pnl_total_usd, 0) AS pnl_total_usd,
  COALESCE(r.pnl_per_trade_usd, 0) AS pnl_per_trade_usd,
  COALESCE(r.avg_entry_price, 0) AS avg_entry_price,
  COALESCE(r.avg_entry_qty, 0) AS avg_entry_qty,
  COALESCE(r.hedged_fired, 0) AS hedge_fired,
  COALESCE(r.sell_fired, 0) AS sell_fired,
  COALESCE(r.partial_sell_fired, 0) AS partial_sell_fired,
  COALESCE(h.hedge_skip_total, 0) AS hedge_skip_total
FROM all_sleeves a
LEFT JOIN signals s     ON a.sleeve_id = s.sleeve_id
LEFT JOIN resolutions r ON a.sleeve_id = r.sleeve_id
LEFT JOIN hedge_skips h ON a.sleeve_id = h.sleeve_id
ORDER BY family, asset, tf, a.sleeve_id;
SQL

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata --csv -f /tmp/all_sleeve_q.sql > "${OUT}"
echo "wrote ${OUT}  ($(wc -l < ${OUT}) lines)"
echo ""
head -3 "${OUT}"
