#!/usr/bin/env bash
# local_pull.sh — DUAL-VPS pull, refresh_2026_05_12.
#
# Architecture (re-verified 2026-05-15):
#   - VPS3 (185.190.143.7): tradingvenue engine; HOSTS the full storedata
#       (orderbook_snapshots_v2 11GB, trades_v2 3.2GB, binance_klines_v2 2.1GB,
#        oracle_prices_v2 593MB, hyperliquid_liquidations_v2 74MB).
#       trading.events partitioned (events_2026_05 / _06).
#       binance feed: binance-spot-ws (live, ~100s lag).
#   - VPS2 (Contabo IPv6): markets catalog 75MB, market_resolutions_v2 14MB,
#       coinbase/kraken/okx klines (in binance_klines_v2 table — yes the table
#       is named binance_* but multi-venue), polymarket collector, hyperliquid_*.
#
# Run from local Git Bash. Idempotent: re-runs overwrite outputs.
#
# Outputs go to: data/v4/refresh_2026_05_12/
#
# Estimated runtime: ~30-45min (server-side aggregations dominate).

set -euo pipefail

LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LOCAL_ROOT"  # ensure relative paths in heredocs resolve correctly
LOCAL_DIR="$LOCAL_ROOT/data/v4/refresh_2026_05_12"
SQL_DIR="$LOCAL_ROOT/migration_2026_05_12/sql"
PREV_SQL_DIR="$LOCAL_ROOT/migration_2026_05_06/sql"
mkdir -p "$LOCAL_DIR" "$LOCAL_DIR/tier1_entries"

VPS2_KEY="${HOME}/.ssh/vps2_ed25519"
VPS2_HOST="root@[2605:a140:2323:6975::1]"
VPS3_KEY="${HOME}/.ssh/vps3_ed25519"
VPS3_HOST="root@185.190.143.7"
DB="storedata"

# --- helpers ---------------------------------------------------------------

ssh_csv() {
    local key="$1" host="$2" sql="$3" outfile="$4"
    echo "  → $(basename "$outfile")"
    ssh -i "$key" "$host" \
        "sudo -u postgres psql -d $DB -c \"COPY ($sql) TO STDOUT WITH CSV HEADER\"" \
        > "$outfile"
    local lines size
    lines=$(wc -l < "$outfile" || echo 0)
    size=$(du -h "$outfile" 2>/dev/null | cut -f1 || echo "?")
    echo "    $lines lines, $size"
}

ssh_run_sql_file() {
    local key="$1" host="$2" sqlfile="$3" asset="$4" outfile="$5"
    local remote_sql="/tmp/$(basename "$sqlfile")"
    echo "  → $(basename "$outfile")  ($(basename "$sqlfile") asset=$asset)"
    scp -q -i "$key" "$sqlfile" "$host:$remote_sql"
    ssh -i "$key" "$host" \
        "sudo -u postgres psql -d $DB -v ASSET=\"'$asset'\" -f $remote_sql" \
        > "$outfile"
    local lines size
    lines=$(wc -l < "$outfile" || echo 0)
    size=$(du -h "$outfile" 2>/dev/null | cut -f1 || echo "?")
    echo "    $lines lines, $size"
}

echo "==============================================================="
echo " DUAL-VPS PULL → $LOCAL_DIR"
echo " Started: $(date -u +%FT%TZ)"
echo "==============================================================="

# --- 1. markets (VPS2) ------------------------------------------------------
echo
echo "[1/11] markets catalog (VPS2)..."
ssh_csv "$VPS2_KEY" "$VPS2_HOST" \
    "SELECT slug, market_id, platform, condition_id, clob_token_ids, outcome_yes, outcome_no,
            resolve_at, resolved_at, outcome, status, created_at, ticker, timeframe
       FROM markets
   ORDER BY created_at" \
    "$LOCAL_DIR/markets_full.csv"

# --- 2. market_resolutions_v2 (VPS2) ---------------------------------------
echo
echo "[2/11] market_resolutions_v2 (VPS2) — 30d window..."
ssh_csv "$VPS2_KEY" "$VPS2_HOST" \
    "SELECT market_id, slug, ticker, timeframe,
            slot_start_us, slot_end_us, outcome,
            outcome_yes_price, outcome_no_price, last_trade_price,
            recorded_at, COALESCE(resolution_source, 'unknown') AS resolution_source,
            strike_price, settlement_price, price_source
       FROM market_resolutions_v2
      WHERE (slug LIKE 'btc-updown-%' OR slug LIKE 'eth-updown-%' OR slug LIKE 'sol-updown-%')
        AND slot_start_us > (EXTRACT(EPOCH FROM (NOW() - INTERVAL '30 days')) * 1e6)::bigint
   ORDER BY slot_start_us" \
    "$LOCAL_DIR/market_resolutions_full.csv"

# --- 3. binance klines (VPS3) ----------------------------------------------
echo
echo "[3/11] binance klines from VPS3 (1MIN/5MIN/15MIN/1HRS, 30d)..."
ssh_csv "$VPS3_KEY" "$VPS3_HOST" \
    "SELECT symbol_id, period_id, source,
            time_period_start_us, time_period_end_us,
            price_open, price_high, price_low, price_close,
            volume_traded, trades_count, quote_volume,
            taker_buy_base, taker_buy_quote
       FROM binance_klines_v2
      WHERE symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
        AND period_id IN ('1MIN','5MIN','15MIN','1HRS')
        AND time_period_start_us > (EXTRACT(EPOCH FROM (NOW() - INTERVAL '30 days')) * 1e6)::bigint
   ORDER BY symbol_id, period_id, time_period_start_us" \
    "$LOCAL_DIR/binance_klines_vps3.csv"

# --- 4. multi-venue klines (VPS2) ------------------------------------------
echo
echo "[4/11] multi-venue klines from VPS2 (coinbase/kraken/okx, 1MIN/5MIN/15MIN, 30d)..."
ssh_csv "$VPS2_KEY" "$VPS2_HOST" \
    "SELECT symbol_id, period_id, source,
            time_period_start_us, time_period_end_us,
            price_open, price_high, price_low, price_close,
            volume_traded, trades_count, quote_volume
       FROM binance_klines_v2
      WHERE symbol_id IN ('COINBASE_SPOT_BTC_USD','COINBASE_SPOT_ETH_USD','COINBASE_SPOT_SOL_USD',
                          'KRAKEN_SPOT_BTC_USD','KRAKEN_SPOT_ETH_USD','KRAKEN_SPOT_SOL_USD',
                          'OKX_SPOT_BTC_USDT','OKX_SPOT_ETH_USDT','OKX_SPOT_SOL_USDT')
        AND period_id IN ('1MIN','5MIN','15MIN')
        AND time_period_start_us > (EXTRACT(EPOCH FROM (NOW() - INTERVAL '30 days')) * 1e6)::bigint
   ORDER BY symbol_id, period_id, time_period_start_us" \
    "$LOCAL_DIR/cex_klines_vps2.csv"

# --- 5. oracle_prices_v2 (VPS3 — primary, deeper) --------------------------
echo
echo "[5/11] oracle_prices_v2 (Chainlink polymarket-rtds, VPS3 30d)..."
ssh_csv "$VPS3_KEY" "$VPS3_HOST" \
    "SELECT symbol_id, source, timestamp_us, local_timestamp_us, price_value
       FROM oracle_prices_v2
      WHERE timestamp_us > (EXTRACT(EPOCH FROM (NOW() - INTERVAL '30 days')) * 1e6)::bigint
   ORDER BY symbol_id, timestamp_us" \
    "$LOCAL_DIR/oracle_prices_full.csv"

# --- 6. universe_lookup for tier1 entries SQL ------------------------------
echo
echo "[6/11] building universe_lookup_full.csv from resolutions (asset,slug,outcome,target_ts_us=t+120s)..."
python - <<'PYEOF'
import csv, os, re
src = os.path.join("data/v4/refresh_2026_05_12", "market_resolutions_full.csv")
dst = os.path.join("data/v4/refresh_2026_05_12", "tier1_entries", "universe_lookup_full.csv")
PAT = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")
n_in = n_out = 0
with open(src, newline="") as fi, open(dst, "w", newline="") as fo:
    r = csv.DictReader(fi)
    w = csv.writer(fo)
    w.writerow(["asset","slug","outcome","target_ts_us"])
    for row in r:
        n_in += 1
        m = PAT.match(row["slug"])
        if not m: continue
        asset, _tf, ws_unix = m.group(1), m.group(2), int(m.group(3))
        target_ts_us = ws_unix * 1_000_000 + 120 * 1_000_000  # t+120s
        w.writerow([asset, row["slug"], "Up",   target_ts_us])
        w.writerow([asset, row["slug"], "Down", target_ts_us])
        n_out += 1
print(f"    universe rows: in={n_in}, markets_emitted={n_out}, lookup_rows={n_out*2}")
PYEOF

# --- 7. tier1 L25 entries (VPS3 server-side, JOIN on slug+outcome) ---------
# NOTE: moved from VPS2 to VPS3 since VPS3 hosts the full orderbook_snapshots_v2 (11GB)
echo
echo "[7/11] tier1 L25 entries at t+120s (server-side join, VPS3)..."
echo "    → uploading universe_lookup_full.csv to VPS3:/tmp/"
scp -q -i "$VPS3_KEY" \
    "$LOCAL_DIR/tier1_entries/universe_lookup_full.csv" \
    "$VPS3_HOST:/tmp/universe_lookup_full.csv"
echo "    → uploading wrapper SQL"
scp -q -i "$VPS3_KEY" \
    "$SQL_DIR/pull_tier1_full_stdout.sql" \
    "$VPS3_HOST:/tmp/pull_tier1_full_stdout.sql"
echo "    → running tier1 join (slow leg, ~5-15min)..."
ssh -i "$VPS3_KEY" "$VPS3_HOST" \
    "sudo -u postgres psql -d $DB -q -f /tmp/pull_tier1_full_stdout.sql" \
    > "$LOCAL_DIR/tier1_entries/tier1_entries_full.csv"
echo "    tier1 rows: $(wc -l < "$LOCAL_DIR/tier1_entries/tier1_entries_full.csv")"
echo "    size: $(du -h "$LOCAL_DIR/tier1_entries/tier1_entries_full.csv" | cut -f1)"

# --- 8. orderbook FLOW features (server-side aggregation, VPS3) ------------
echo
echo "[8/11] orderbook FLOW features (server-side aggregation, VPS3)..."
for asset in btc eth sol; do
    ssh_run_sql_file "$VPS3_KEY" "$VPS3_HOST" \
        "$PREV_SQL_DIR/flow_features_orderbook.sql" "$asset" \
        "$LOCAL_DIR/${asset}_flow_orderbook.csv"
done

# --- 9. trades CVD/aggressor (server-side aggregation, VPS3) ---------------
echo
echo "[9/11] trades CVD/aggressor features (server-side aggregation, VPS3)..."
for asset in btc eth sol; do
    ssh_run_sql_file "$VPS3_KEY" "$VPS3_HOST" \
        "$PREV_SQL_DIR/flow_features_trades.sql" "$asset" \
        "$LOCAL_DIR/${asset}_flow_trades.csv"
done

# --- 10. trading.events full window (VPS3, last 14 days) -------------------
echo
echo "[10/11] VPS3 trading.events (last 14 days — full audit history for sleeve analytics)..."
ssh_csv "$VPS3_KEY" "$VPS3_HOST" \
    "SELECT at, kind, sleeve_id, position_id::text AS position_id, order_id::text AS order_id, data
       FROM trading.events
      WHERE at > NOW() - INTERVAL '14 days'
   ORDER BY at" \
    "$LOCAL_DIR/vps3_trading_events_14d.csv"

# --- 11. hyperliquid liquidations (VPS3, for triggers) --------------------
echo
echo "[11/11] hyperliquid_liquidations (BTC/ETH/SOL, VPS3)..."
ssh_csv "$VPS3_KEY" "$VPS3_HOST" \
    "SELECT coin, side, dir, price, size, mark_price, closed_pnl, fee,
            time_exchange_us, source
       FROM hyperliquid_liquidations_v2
      WHERE coin IN ('BTC','ETH','SOL')
        AND time_exchange_us > (EXTRACT(EPOCH FROM (NOW() - INTERVAL '30 days')) * 1e6)::bigint
   ORDER BY coin, time_exchange_us" \
    "$LOCAL_DIR/hl_liquidations_btc_eth_sol.csv"

# --- summary ---------------------------------------------------------------
echo
echo "==============================================================="
echo " DONE — $(date -u +%FT%TZ)"
echo "==============================================================="
ls -lah "$LOCAL_DIR"/*.csv 2>/dev/null | sort -k5 -hr | head -30
echo
ls -lah "$LOCAL_DIR/tier1_entries"/*.csv 2>/dev/null
echo
echo "Total disk used:"
du -sh "$LOCAL_DIR"
