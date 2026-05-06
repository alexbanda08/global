#!/bin/bash
# refresh_and_analyze.sh — Path C re-validation helper
#
# Pulls fresh shadow-trade resolutions from VPS3 (including any new inverse sleeves)
# and re-runs the anti-edge analyzer + v4 cross-reference.
#
# Run weekly. Output goes into a date-stamped directory so each week's snapshot is preserved.
#
# Usage: bash strategy_lab/meta_classifier/refresh_and_analyze.sh

set -uo pipefail

cd "/c/Users/alexandre bandarra/Desktop/global"

DATE=$(date +%Y_%m_%d)
OUTDIR="data/v4/shadow_trades_${DATE}_live"
mkdir -p "$OUTDIR"

# Required env vars — never commit literal credentials.
#   VPS3_HOST          (e.g. "root@185.190.143.7")
#   VPS3_TV_PWD        (Postgres tradingvenue write-user password)
#   VPS3_SSH_KEY       (default: ~/.ssh/vps3_ed25519)
: "${VPS3_HOST:?set VPS3_HOST env var}"
: "${VPS3_TV_PWD:?set VPS3_TV_PWD env var}"
: "${VPS3_SSH_KEY:=$HOME/.ssh/vps3_ed25519}"

echo "=== refresh_and_analyze.sh: $DATE ==="
echo "Output dir: $OUTDIR"
echo

# ── 1. Pull fresh ALL-sleeve resolutions (winners + losers + inverse if deployed)
echo "[1] Pulling fresh resolutions from VPS3..."
ssh -i "$VPS3_SSH_KEY" -o ConnectTimeout=10 "$VPS3_HOST" \
  "PGPASSWORD=$VPS3_TV_PWD psql -h 127.0.0.1 -U tradingvenue -d storedata -A -F, -P pager=off > /tmp/all_resolutions.csv <<'SQL'
COPY (
  SELECT
    sleeve_id, at,
    (data->>'symbol') AS symbol, (data->>'tf') AS tf,
    (data->>'signal') AS signal, (data->>'outcome') AS outcome,
    (data->>'won')::boolean AS won,
    (data->>'pnl_usd')::numeric AS pnl_usd,
    (data->>'entry_price')::numeric AS entry_price,
    (data->>'hedged')::boolean AS hedged,
    (data->>'condition_id') AS condition_id,
    (data->>'strike_price')::numeric AS strike_price,
    (data->>'settlement_price')::numeric AS settlement_price,
    (data->>'price_source') AS price_source,
    (data->>'strategy_mode') AS strategy_mode,
    (data->>'base_signal') AS base_signal,
    EXTRACT(hour FROM at AT TIME ZONE 'UTC')::int AS hour_utc,
    EXTRACT(dow FROM at AT TIME ZONE 'UTC')::int AS dow_utc
  FROM trading.events
  WHERE kind = 'poly_updown_resolution'
  ORDER BY sleeve_id, at
) TO STDOUT WITH (FORMAT CSV, HEADER true)
SQL
ls -la /tmp/all_resolutions.csv && wc -l /tmp/all_resolutions.csv"

scp -i "$VPS3_SSH_KEY" "$VPS3_HOST:/tmp/all_resolutions.csv" "$OUTDIR/all_resolutions.csv"
echo "  Downloaded: $(wc -l < $OUTDIR/all_resolutions.csv) lines to $OUTDIR/all_resolutions.csv"

# ── 2. Split into losing-sleeves vs inverse-sleeves vs winners for clear analysis
echo
echo "[2] Splitting by sleeve category..."
py - <<PYEOF
import pandas as pd
df = pd.read_csv("$OUTDIR/all_resolutions.csv")
df["won"] = df["won"].map({"t":1, "f":0})
print(f"Total resolutions: {len(df)}")
print(f"Date range: {df['at'].min()} -> {df['at'].max()}")
print()
print("=== ALL SLEEVES ===")
agg = df.groupby("sleeve_id").agg(
    n=("won","count"), wins=("won","sum"),
    pnl=("pnl_usd","sum"),
).reset_index()
agg["hit"] = (agg["wins"]/agg["n"]*100).round(1)
agg["pnl_per"] = (agg["pnl"]/agg["n"]).round(2)
agg = agg.sort_values("pnl", ascending=False)
print(agg.to_string(index=False))
print()

# Split
inverse = df[df["sleeve_id"].str.contains("_INV", na=False)]
v3v4 = df[df["sleeve_id"].str.contains("_v3|_v4", na=False)]
losers = df[df["sleeve_id"].isin([
    "poly_updown_sol_5m_volume","poly_updown_eth_5m_volume","poly_updown_btc_5m_volume",
    "poly_updown_sol_15m_volume","poly_updown_eth_15m_volume","poly_updown_btc_15m_volume",
    "poly_updown_sol_5m_sniper","poly_updown_eth_5m_sniper",
])]
print(f"\nInverse sleeve trades: {len(inverse)}")
print(f"v3/v4 winner trades:   {len(v3v4)}")
print(f"Original loser trades: {len(losers)}")

inverse.to_csv("$OUTDIR/inverse_sleeves.csv", index=False)
v3v4.to_csv("$OUTDIR/v3_v4_resolutions.csv", index=False)
losers.to_csv("$OUTDIR/losing_sleeves.csv", index=False)
PYEOF

# ── 3. Re-run anti-edge analyzer on the LOSERS (control group — should still show same biases)
echo
echo "[3] Re-running anti_edge_analyzer.py on original losers..."
LOSERS_PATH="$OUTDIR/losing_sleeves.csv" \
  py strategy_lab/meta_classifier/anti_edge_analyzer.py 2>&1 | tee "$OUTDIR/anti_edge_analysis.log"

# ── 4. If inverse sleeves are deployed, evaluate their performance vs predictions
if [ -s "$OUTDIR/inverse_sleeves.csv" ] && [ $(wc -l < "$OUTDIR/inverse_sleeves.csv") -gt 1 ]; then
    echo
    echo "[4] INVERSE SLEEVES detected — running validation..."
    py - <<PYEOF
import pandas as pd
inv = pd.read_csv("$OUTDIR/inverse_sleeves.csv")
inv["won"] = inv["won"].map({"t":1, "f":0})
print(f"\n=== INVERSE SLEEVE VALIDATION ===")
print(f"Total inverse trades: {len(inv)}")
print()
agg = inv.groupby("sleeve_id").agg(
    n=("won","count"), wins=("won","sum"),
    pnl=("pnl_usd","sum"),
).reset_index()
agg["hit_pct"] = (agg["wins"]/agg["n"]*100).round(1)
agg["pnl_per_trade"] = (agg["pnl"]/agg["n"]).round(2)

# Pass criteria from TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md §5
def verdict(row):
    if row["n"] < 50: return "INSUFFICIENT_SAMPLE"
    if row["hit_pct"] < 45: return "FAIL_KILL_SWITCH"
    if row["hit_pct"] < 55: return "WEAK_FAIL_THRESHOLD"
    if row["pnl_per_trade"] < 5: return "WEAK_LOW_PNL"
    return "PASS"

agg["verdict"] = agg.apply(verdict, axis=1)
print(agg.to_string(index=False))
PYEOF
else
    echo "[4] No inverse sleeves deployed yet (or 0 trades). Skipping validation."
fi

echo
echo "=== Done. Snapshot saved to $OUTDIR ==="
echo "Files:"
ls -la "$OUTDIR"
