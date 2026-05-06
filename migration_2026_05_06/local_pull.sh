#!/usr/bin/env bash
# local_pull.sh — pull missing data from VPS2 (which has the complete dataset)
# to local strategy_lab. Run from LOCAL (Windows / Git Bash).
#
# Strategy:
#   - VPS2 is the source of truth (has all data, no live-collector loss issues).
#   - Heavy aggregations run SERVER-SIDE on VPS2 via SSH-piped psql:
#       orderbook 35 GB raw → ~250 MB feature CSV (server-side aggregation)
#       trades    38 GB raw → ~80 MB CVD/aggressor CSV (server-side aggregation)
#   - Other small tables pulled directly.
#
# Outputs go to: data/v4/refresh_2026_05_06/
#
# Total expected size: ~700 MB (vs 5+ GB if pulling raw L25 + raw trades).

set -euo pipefail

LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_DIR="$LOCAL_ROOT/data/v4/refresh_2026_05_06"
SQL_DIR="$LOCAL_ROOT/migration_2026_05_06/sql"
mkdir -p "$LOCAL_DIR"

VPS2_KEY="${HOME}/.ssh/vps2_ed25519"
VPS2_HOST="root@[2605:a140:2323:6975::1]"
VPS2_DB="storedata"

ssh_query_to_csv() {
    # Stream a single SQL statement → CSV file
    local sql="$1"
    local outfile="$2"
    echo "  → $outfile"
    ssh -i "$VPS2_KEY" "$VPS2_HOST" \
        "sudo -u postgres psql -d $VPS2_DB -c \"COPY ($sql) TO STDOUT WITH CSV HEADER\"" \
        > "$outfile"
    local lines
    lines=$(wc -l < "$outfile")
    local size
    size=$(du -h "$outfile" | cut -f1)
    echo "    $lines lines, $size"
}

ssh_run_sql_file() {
    # Upload an SQL file to VPS2, run it server-side with -v ASSET, stream CSV back
    local sqlfile="$1"
    local asset="$2"
    local outfile="$3"
    local remote_sql="/tmp/$(basename "$sqlfile")"

    echo "  → $outfile  ($(basename "$sqlfile") asset=$asset)"
    scp -q -i "$VPS2_KEY" "$sqlfile" "$VPS2_HOST:$remote_sql"
    ssh -i "$VPS2_KEY" "$VPS2_HOST" \
        "sudo -u postgres psql -d $VPS2_DB -v ASSET=\"'$asset'\" -f $remote_sql" \
        > "$outfile"
    local lines
    lines=$(wc -l < "$outfile")
    local size
    size=$(du -h "$outfile" | cut -f1)
    echo "    $lines lines, $size"
}

echo "==============================================================="
echo " LOCAL PULL FROM VPS2 → $LOCAL_DIR"
echo " Started: $(date -u +%FT%TZ)"
echo "==============================================================="

# ----- 1. markets ------------------------------------------------------------
echo
echo "[1/8] markets (full Polymarket UpDown catalog)..."
ssh_query_to_csv \
    "SELECT slug, market_id, platform, condition_id, clob_token_ids, outcome_yes, outcome_no,
            resolve_at, resolved_at, outcome, status, created_at, ticker, timeframe
       FROM markets
   ORDER BY created_at" \
    "$LOCAL_DIR/markets_full.csv"

# ----- 2. market_resolutions_v2 ---------------------------------------------
echo
echo "[2/8] market_resolutions_v2..."
ssh_query_to_csv \
    "SELECT slug, outcome, recorded_at, COALESCE(resolution_source, 'unknown') AS source
       FROM market_resolutions_v2
   ORDER BY recorded_at" \
    "$LOCAL_DIR/market_resolutions_full.csv"

# ----- 3. binance_klines (BTC/ETH/SOL × all periods × all sources) ----------
echo
echo "[3/8] binance_klines_v2 (BTC/ETH/SOL)..."
ssh_query_to_csv \
    "SELECT symbol_id, period_id, source,
            time_period_start_us, time_period_end_us,
            price_open, price_high, price_low, price_close,
            volume_traded, trades_count, quote_volume,
            taker_buy_base, taker_buy_quote
       FROM binance_klines_v2
      WHERE symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
   ORDER BY symbol_id, period_id, time_period_start_us" \
    "$LOCAL_DIR/binance_klines_full.csv"

# ----- 4. oracle_prices_v2 --------------------------------------------------
echo
echo "[4/8] oracle_prices_v2 (Chainlink polymarket-rtds)..."
ssh_query_to_csv \
    "SELECT symbol_id, source, timestamp_us, local_timestamp_us, price_value
       FROM oracle_prices_v2
   ORDER BY symbol_id, timestamp_us" \
    "$LOCAL_DIR/oracle_prices_full.csv"

# ----- 5. orderbook FLOW features (server-side aggregation) ------------------
echo
echo "[5/8] orderbook FLOW features (35GB raw → ~250MB total via server-side aggregation)..."
for asset in btc eth sol; do
    ssh_run_sql_file "$SQL_DIR/flow_features_orderbook.sql" "$asset" \
        "$LOCAL_DIR/${asset}_flow_orderbook.csv"
done

# ----- 6. trades CVD/aggressor features (server-side aggregation) ------------
echo
echo "[6/8] trades CVD/aggressor features (38GB raw → ~80MB total)..."
for asset in btc eth sol; do
    ssh_run_sql_file "$SQL_DIR/flow_features_trades.sql" "$asset" \
        "$LOCAL_DIR/${asset}_flow_trades.csv"
done

# ----- 7. hyperliquid_klines (for Cyclops STRUCTURE — BTC trend) ------------
echo
echo "[7/8] hyperliquid_klines (BTC/ETH/SOL)..."
ssh_query_to_csv \
    "SELECT symbol_id, period_id, source,
            time_period_start_us, time_period_end_us,
            price_open, price_high, price_low, price_close, volume_traded
       FROM hyperliquid_klines_v2
      WHERE symbol_id IN ('HYPERLIQUID_PERP_BTC_USD','HYPERLIQUID_PERP_ETH_USD','HYPERLIQUID_PERP_SOL_USD')
   ORDER BY symbol_id, period_id, time_period_start_us" \
    "$LOCAL_DIR/hl_klines_full.csv" || echo "    (table empty or symbol mapping different — non-fatal)"

# ----- 8. hyperliquid_liquidations (BTC/ETH/SOL only — for triggers) --------
echo
echo "[8/8] hyperliquid_liquidations (BTC/ETH/SOL — Layer 3 triggers)..."
ssh_query_to_csv \
    "SELECT coin, side, dir, price, size, mark_price, closed_pnl, fee,
            time_exchange_us, source
       FROM hyperliquid_liquidations_v2
      WHERE coin IN ('BTC','ETH','SOL')
   ORDER BY coin, time_exchange_us" \
    "$LOCAL_DIR/hl_liquidations_btc_eth_sol.csv"

# ----- Summary --------------------------------------------------------------
echo
echo "==============================================================="
echo " DONE — $(date -u +%FT%TZ)"
echo "==============================================================="
ls -lah "$LOCAL_DIR"/*.csv 2>/dev/null | sort -k5 -hr
echo
echo "Total disk used:"
du -sh "$LOCAL_DIR"
echo
echo "Next step: gzip the largest files to save disk:"
echo "  gzip $LOCAL_DIR/*_flow_orderbook.csv  $LOCAL_DIR/*_flow_trades.csv"
