#!/usr/bin/env bash
# pull_raw_L25.sh — pull RAW L25 orderbook (every snapshot, all 25 levels)
# and RAW trades from VPS2. NO aggregation. Streams gzipped CSV.
#
# Output:
#   {btc,eth,sol}_orderbook_raw_L25.csv.gz  (every snapshot, all 50 L25 cols)
#   {btc,eth,sol}_trades_raw.csv.gz         (every trade tick)
#
# Expected sizes (gzipped):
#   BTC orderbook ~6-8 GB, ETH ~1.5 GB, SOL ~600 MB
#   BTC trades ~400 MB, ETH ~150 MB, SOL ~80 MB
#   TOTAL ~10 GB

set -euo pipefail

LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/v4/refresh_2026_05_06"
mkdir -p "$LOCAL_DIR"

VPS2_KEY="${HOME}/.ssh/vps2_ed25519"
VPS2_HOST="root@[2605:a140:2323:6975::1]"

stream_table_to_gz() {
    # $1 = table, $2 = WHERE clause, $3 = output filename (.csv.gz)
    local table="$1"
    local where="$2"
    local outfile="$3"
    local started
    started=$(date +%s)
    echo "  ▶ $outfile"
    ssh -i "$VPS2_KEY" "$VPS2_HOST" \
        "sudo -u postgres psql -d storedata -c \"COPY (SELECT * FROM ${table} WHERE ${where} ORDER BY timestamp_us) TO STDOUT WITH CSV HEADER\"" \
        | gzip -1 \
        > "$outfile"
    local ended
    ended=$(date +%s)
    local elapsed=$((ended - started))
    local size
    size=$(du -h "$outfile" | cut -f1)
    echo "    ✓ $size in ${elapsed}s"
}

echo "==============================================================="
echo " RAW L25 PULL — every snapshot, all 25 levels, no aggregation"
echo " Started: $(date -u +%FT%TZ)"
echo "==============================================================="

# Run 3 assets in parallel? NO — single SSH pipe is faster end-to-end than
# 3 contending for VPS2 disk I/O on the same partitioned table. Sequential
# is actually optimal for this workload.

# Order: SOL first (smallest, validates pipeline), then ETH, then BTC.
echo
echo "[1/6] SOL orderbook raw L25 (~2.3M rows, ~600 MB gz)..."
stream_table_to_gz orderbook_snapshots_v2 \
    "slug LIKE 'sol-updown-%'" \
    "$LOCAL_DIR/sol_orderbook_raw_L25.csv.gz"

echo
echo "[2/6] ETH orderbook raw L25 (~5.3M rows, ~1.5 GB gz)..."
stream_table_to_gz orderbook_snapshots_v2 \
    "slug LIKE 'eth-updown-%'" \
    "$LOCAL_DIR/eth_orderbook_raw_L25.csv.gz"

echo
echo "[3/6] BTC orderbook raw L25 (~28M rows, ~6-8 GB gz, slowest step ~30-60min)..."
stream_table_to_gz orderbook_snapshots_v2 \
    "slug LIKE 'btc-updown-%'" \
    "$LOCAL_DIR/btc_orderbook_raw_L25.csv.gz"

echo
echo "[4/6] SOL trades raw (every tick)..."
stream_table_to_gz trades_v2 \
    "slug LIKE 'sol-updown-%'" \
    "$LOCAL_DIR/sol_trades_raw.csv.gz"

echo
echo "[5/6] ETH trades raw..."
stream_table_to_gz trades_v2 \
    "slug LIKE 'eth-updown-%'" \
    "$LOCAL_DIR/eth_trades_raw.csv.gz"

echo
echo "[6/6] BTC trades raw..."
stream_table_to_gz trades_v2 \
    "slug LIKE 'btc-updown-%'" \
    "$LOCAL_DIR/btc_trades_raw.csv.gz"

echo
echo "==============================================================="
echo " DONE — $(date -u +%FT%TZ)"
echo "==============================================================="
ls -lah "$LOCAL_DIR"/*_raw_L25.csv.gz "$LOCAL_DIR"/*_trades_raw.csv.gz 2>&1 | sort -k5 -hr
echo
du -sh "$LOCAL_DIR"
echo
echo "Sanity check: count rows in SOL gz file (should match VPS2)..."
zcat "$LOCAL_DIR/sol_orderbook_raw_L25.csv.gz" | wc -l
