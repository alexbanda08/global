"""Re-run backtest with realistic qty_compute approximations.

Adds:
  1. Min-notional / lot-size: Polymarket requires ≥5 shares per fill (CLAUDE.md
     inv #7). Round shares to nearest 5, reject if would be < 5.
  2. Per-slug max position: at most ONE fire per slug per sleeve_id.
  3. Wallet/USDC balance gating: track running balance per sleeve; can't fire if
     would exceed allocated capital. Use simple per-sleeve $500 initial capital
     with 24h slot resolution capital recycling.
  4. Min-fill-fraction: if book walk fills < 50% of notional, reject (already in
     engine_v2 but enforce per fire explicitly).

These approximate the production qty_compute_failed reasons that dropped
~30× of the fires in my unfiltered backtest.

Output: scorecard with new fire counts compared to (a) my unfiltered backtest,
(b) production 7d numbers.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

OUT_DIR = Path("strategy_lab/markov_filter/_results/backtest_realistic_qty")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Production-mimic constraints
NOTIONAL_USD = 25.0
MIN_SHARES = 5
PER_SLEEVE_CAPITAL_USD = 500.0   # max in-flight capital per (sleeve_id, asset, tf)
MIN_FILL_FRACTION = 0.5

print("[1] Loading existing fills (with all gate columns from prior runs)...")
fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
print(f"   {len(fills):,} fills loaded")
# Compute fire_ts for ordering and slot tracking
fills["fire_ts"] = pd.to_datetime(fills["fire_us"], unit="us", utc=True)
fills = fills.sort_values("fire_us").reset_index(drop=True)

# Min-shares gate: reject if shares < 5 OR if rounding down to lot of 5 leaves < 5
fills["shares_rounded"] = (fills["shares"] // MIN_SHARES) * MIN_SHARES
fills["min_shares_pass"] = fills["shares_rounded"] >= MIN_SHARES

# Min-fill-fraction gate: usd actually walked / notional
fills["fill_fraction"] = fills["usd"] / NOTIONAL_USD
fills["min_fill_pass"] = fills["fill_fraction"] >= MIN_FILL_FRACTION

# Per-slug × sleeve_id dedup (one fire per slug per sleeve)
fills["sleeve_key"] = fills["strategy"] + "_" + fills["cell"]
# pick the FIRST event per (sleeve_key, slug)
fills["per_slug_first"] = ~fills.duplicated(subset=["sleeve_key", "slug"], keep="first")

# Per-sleeve capital tracking: simulate FIFO capital usage; assume capital frees
# at slot_end (so 5m fires hold for ~3min, 15m for ~8min). Conservative model:
# capital is "locked" until slot_end_us.
fills["slot_end_us"] = (fills["slot_end_us"] if "slot_end_us" in fills.columns else None)
# Reload from universe to get slot_end if missing
if "slot_end_us" not in fills.columns or fills["slot_end_us"].isna().any():
    print("   adding slot_end_us from universe.csv")
    u = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/universe.csv")
    u["slot_end_us"] = u["slot_end_s"] * 1_000_000
    fills = fills.merge(u[["slug","slot_end_us"]].drop_duplicates("slug"),
                        on="slug", how="left", suffixes=("","_u"))
    if "slot_end_us_u" in fills.columns:
        fills["slot_end_us"] = fills["slot_end_us_u"]

# Simulate capital tracking per sleeve_key
print("[2] Simulating per-sleeve capital tracking...")
fills["capital_pass"] = False
for skey, g in fills.groupby("sleeve_key"):
    g = g.sort_values("fire_us")
    # Walk forward: at each fire, free any capital from slots that already ended
    in_flight = []   # list of (release_us, usd)
    used_total = 0.0
    keep = []
    for _, r in g.iterrows():
        # Release expired capital
        in_flight = [(t, u) for (t, u) in in_flight if t > r["fire_us"]]
        used_total = sum(u for _, u in in_flight)
        if used_total + NOTIONAL_USD <= PER_SLEEVE_CAPITAL_USD:
            keep.append(True)
            in_flight.append((r["slot_end_us"] if pd.notna(r["slot_end_us"]) else r["fire_us"] + 600_000_000, NOTIONAL_USD))
        else:
            keep.append(False)
    fills.loc[g.index, "capital_pass"] = keep

# Combined pass: all 4 gates AND per-slug-first
fills["realistic_qty_pass"] = (
    fills["min_shares_pass"] &
    fills["min_fill_pass"] &
    fills["per_slug_first"] &
    fills["capital_pass"]
)

n_pre = len(fills)
n_post = fills["realistic_qty_pass"].sum()
print(f"\n[3] Filter impact:")
print(f"   pre-filter: {n_pre:,} fills")
print(f"   min_shares (≥5):   pass {fills['min_shares_pass'].sum():,} ({fills['min_shares_pass'].mean()*100:.1f}%)")
print(f"   min_fill (≥50%):   pass {fills['min_fill_pass'].sum():,} ({fills['min_fill_pass'].mean()*100:.1f}%)")
print(f"   per-slug-first:    pass {fills['per_slug_first'].sum():,} ({fills['per_slug_first'].mean()*100:.1f}%)")
print(f"   capital ($500/sleeve): pass {fills['capital_pass'].sum():,} ({fills['capital_pass'].mean()*100:.1f}%)")
print(f"   COMBINED pass:     {n_post:,} ({n_post/n_pre*100:.1f}%)")

# Save the realistic-fills
realistic = fills[fills["realistic_qty_pass"]].copy()
realistic.to_csv(OUT_DIR / "realistic_fills.csv", index=False)

# Re-score per (strategy, cell) with realistic universe
print("\n[4] Per-sleeve scorecard on realistic universe (NO gates, just realistic qty)...")
rows = []
for (strat, cell), g in realistic.groupby(["strategy", "cell"]):
    if len(g) < 5: continue
    rows.append({
        "strategy": strat, "cell": cell,
        "n_realistic": len(g),
        "wr": round(g["won"].mean()*100, 2),
        "avg": round(g["pnl"].mean(), 3),
        "sum": round(g["pnl"].sum(), 2),
        "fires_per_day": round(len(g) / 28, 2),
    })
sc = pd.DataFrame(rows).sort_values("sum", ascending=False)
print(sc.to_string(index=False))

# Compare to production 7d numbers
print("\n[5] Comparison to production 7d order_placed rates...")
prod = pd.read_csv("strategy_lab/markov_filter/_vps3_pull/PROD_FIRE_REASON_BREAKDOWN.csv")
prod_placed = prod[prod["reason"] == "order_placed"].copy()
prod_placed["per_day"] = prod_placed["n"] / 7  # 7-day window
prod_placed["cell"] = prod_placed["sleeve_group"].str.replace("_momo_v2","").str.replace("_momo","")
prod_placed["strategy"] = np.where(
    prod_placed["family"]=="momo_v2", "momo_v2",
    np.where(prod_placed["family"]=="momo_v1", "momo_v1",
             prod_placed["family"]))
# join
cmp = sc.merge(
    prod_placed[["strategy","cell","per_day"]].rename(columns={"per_day": "prod_per_day"}),
    on=["strategy","cell"], how="left"
)
cmp["ratio"] = (cmp["fires_per_day"] / cmp["prod_per_day"]).round(2)
print(cmp.to_string(index=False))
cmp.to_csv(OUT_DIR / "fire_rate_comparison.csv", index=False)

print(f"\n[6] Re-scoring HoD + gate stacks on realistic universe...")
# Re-apply the mega-stack gates on the realistic-pass subset
realistic["fire_ts"] = pd.to_datetime(realistic["fire_us"], unit="us", utc=True)
realistic["hour"] = realistic["fire_ts"].dt.hour
realistic["cell_key"] = realistic["asset"].str.lower() + "_" + realistic["tf"]

# HoD top-8 per (strategy, cell) - using same locked list as spec
HOD_LISTS = {
    ("sniper","sol_5m"): [0,1,2,4,8,15,19,23],
    ("sniper","eth_15m"): [0,6,7,9,13,14,19,22],
    ("momo_v1","btc_15m"): [0,1,3,5,9,14,16,20],
    ("sniper","btc_15m"): [0,3,10,11,12,13,14,15],
    ("sniper","btc_5m"): [0,1,3,5,12,15,19,21],
    ("momo_v2","btc_5m"): [0,2,5,6,10,12,21,23],
    ("momo_v2","btc_15m"): [1,11,12,16,18,20,21,22],
    ("momo_v2","sol_5m"): [4,5,6,8,10,12,14,17],
    ("momo_v2","eth_15m"): [0,5,8,12,16,17,20,22],
    ("momo_v2","sol_15m"): [1,2,5,12,13,16,17,21],
    ("sniper","eth_5m"): [0,2,11,13,14,17,20,21],
}

print("\nDeploy-spec sleeves on REALISTIC universe:")
print(f"{'sleeve':<35}{'n_real':>8}{'fires/d':>10}{'WR%':>8}{'$/tr':>10}{'sum':>10}")
deploy_rows = []
for (strat, cell), hours in HOD_LISTS.items():
    g = realistic[(realistic["strategy"]==strat) & (realistic["cell_key"]==cell)]
    if g.empty: continue
    g_hod = g[g["hour"].isin(hours)]
    if len(g_hod) < 5: continue
    name = f"{strat}_{cell}_hod"
    deploy_rows.append({
        "sleeve": name, "n_realistic": len(g_hod),
        "fires_per_day": round(len(g_hod)/28, 2),
        "wr": round(g_hod["won"].mean()*100, 2),
        "avg": round(g_hod["pnl"].mean(), 3),
        "sum": round(g_hod["pnl"].sum(), 2),
    })
    print(f"{name:<35}{len(g_hod):>8}{len(g_hod)/28:>10.2f}{g_hod['won'].mean()*100:>8.1f}{g_hod['pnl'].mean():>+10.2f}{g_hod['pnl'].sum():>+10.0f}")

deploy_df = pd.DataFrame(deploy_rows)
deploy_df.to_csv(OUT_DIR / "deploy_sleeves_realistic.csv", index=False)
print(f"\nTotal projected sum (realistic, 28d): ${deploy_df['sum'].sum():.0f}")
print(f"Total projected fires/day: {deploy_df['fires_per_day'].sum():.1f}")
