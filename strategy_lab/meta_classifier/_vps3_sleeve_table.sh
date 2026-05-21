#!/bin/bash
# Comprehensive per-sleeve aggregation across all 36 momo sleeves.
# Outputs CSV via psql -A -F, redirection (avoids \copy single-line limit).
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

OUT=/tmp/momo_sleeve_stats.csv

# Write the SQL to a temp file so psql can read multi-line CTEs without \copy.
cat > /tmp/sleeve_q.sql <<'SQL'
WITH base AS (
  SELECT sleeve_id, kind, at, data
  FROM trading.events
  WHERE at > now() - interval '14 days'
    AND sleeve_id LIKE '%momo%'
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
)
SELECT
  s.sleeve_id,
  split_part(s.sleeve_id, '_', 3) AS asset,
  split_part(s.sleeve_id, '_', 4) AS tf,
  CASE WHEN s.sleeve_id LIKE '%momo_v2_%' THEN 'v2' ELSE 'v1' END AS version,
  CASE WHEN s.sleeve_id LIKE '%momo_v2_%'
       THEN split_part(s.sleeve_id, '_', 7)
       ELSE split_part(s.sleeve_id, '_', 6) END AS policy,
  s.first_signal_at,
  s.last_signal_at,
  round(EXTRACT(EPOCH FROM (s.last_signal_at - s.first_signal_at)) / 3600.0, 2) AS hours_running,
  s.signals_total,
  s.signals_fired,
  s.signals_skipped,
  round(s.signals_fired::numeric * 100 / NULLIF(s.signals_total,0), 2) AS fire_rate_pct,
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
  COALESCE(h.hedge_skip_total, 0) AS hedge_skip_total,
  round(COALESCE(r.hedged_fired,0)::numeric * 100 / NULLIF(r.resolved,0), 2) AS hedge_fire_rate_pct,
  round(COALESCE(r.sell_fired,0)::numeric * 100 / NULLIF(r.resolved,0), 2) AS sell_fire_rate_pct
FROM signals s
LEFT JOIN resolutions r ON s.sleeve_id = r.sleeve_id
LEFT JOIN hedge_skips  h ON s.sleeve_id = h.sleeve_id
ORDER BY version, asset, tf, policy;
SQL

# Run with unaligned + CSV output, pipe to file. Use --csv (PG 12+).
psql -h 127.0.0.1 -U tradingvenue_ro -d storedata --csv -f /tmp/sleeve_q.sql > "${OUT}"
echo "wrote ${OUT}  ($(wc -l < ${OUT}) lines)"
echo ""
echo "=== preview first 3 rows ==="
head -4 "${OUT}"
