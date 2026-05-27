"""
HL Gates Refinement — lower threshold sweep + asset-split
2026-05-27

Reuses same fire universe (fired_by_sleeve.parquet, seed=42, n=5000).
Tests SHORT cascade at $10k/$20k/$50k/$100k/$200k × 60/180/300/600s
     LONG  cascade at $10k/$20k/$50k/$100k       × 60/180/300/600s
Also splits by matching asset (BTC fires vs BTC liqs, etc.)
"""

import sys
import time
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical")

import pandas as pd
import numpy as np
from pathlib import Path

t0 = time.time()

# ─── 0. Fire universe (same sampling as v2) ───────────────────────────────────
print("Loading fire universe...", flush=True)
fires = pd.read_parquet(
    "C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7/fired_by_sleeve.parquet"
)
fires["dir"] = fires["direction"].map({"UP": "Up", "DOWN": "Down"})

rng = np.random.default_rng(42)
if len(fires) > 5000:
    idx = rng.choice(len(fires), size=5000, replace=False)
    sample = fires.iloc[idx].reset_index(drop=True).copy()
else:
    sample = fires.copy()

sample["fire_us_int"] = sample["fire_us"].astype(np.int64)
BASELINE_WR = sample["won"].mean()
print(f"  n={len(sample)}, WR_baseline={BASELINE_WR:.4f}", flush=True)

# ─── 1. Load HL liquidations ──────────────────────────────────────────────────
print("Loading HL liquidations...", flush=True)
from load import load_hyperliquid_liquidations_full

hl_raw = load_hyperliquid_liquidations_full()
print(f"  Raw rows: {len(hl_raw)}", flush=True)

# LONG proxy: Close Long from hl-userevents-ws → predicts DOWN
hl_long = hl_raw[
    (hl_raw["coin"].isin(["BTC", "ETH", "SOL"])) &
    (hl_raw["source"] == "hl-userevents-ws") &
    (hl_raw["dir"] == "Close Long")
].copy()
hl_long["usd"] = hl_long["size"] * hl_long["price"]

# SHORT proxy: Close Short market from hl-s3-fills → predicts UP
hl_short = hl_raw[
    (hl_raw["coin"].isin(["BTC", "ETH", "SOL"])) &
    (hl_raw["source"] == "hl-s3-fills") &
    (hl_raw["method"] == "market") &
    (hl_raw["dir"] == "Close Short")
].copy()
hl_short["usd"] = hl_short["size"] * hl_short["price"]

hl_long  = hl_long.sort_values("time_exchange_us").reset_index(drop=True)
hl_short = hl_short.sort_values("time_exchange_us").reset_index(drop=True)

print(f"  LONG proxy rows: {len(hl_long)} | USD median: ${hl_long['usd'].median():.0f}", flush=True)
print(f"  SHORT proxy rows: {len(hl_short)} | USD median: ${hl_short['usd'].median():.0f}", flush=True)

# Pre-group by asset
hl_groups = {}
for asset in ["BTC", "ETH", "SOL"]:
    hl_groups[(asset, "LONG")]  = hl_long[hl_long["coin"] == asset].copy()
    hl_groups[(asset, "SHORT")] = hl_short[hl_short["coin"] == asset].copy()

# ─── 2. Build cumulative USD per fire × window using searchsorted ─────────────
print("Computing cascade features...", flush=True)

SHORT_THRESHOLDS = [10_000, 20_000, 50_000, 100_000, 200_000]
LONG_THRESHOLDS  = [10_000, 20_000, 50_000, 100_000]
WINDOWS = [60, 180, 300, 600]

fire_us_arr = sample["fire_us_int"].values
asset_arr   = sample["asset"].values
won_arr     = sample["won"].values
dir_arr     = sample["dir"].values

def compute_usd_col(liq_type, window_s):
    """Return array of cumulative USD per fire row (all-assets mixed)."""
    vals = np.zeros(len(sample), dtype=np.float64)
    for asset in ["BTC", "ETH", "SOL"]:
        mask = (asset_arr == asset)
        if not mask.any():
            continue
        sub = hl_groups.get((asset, liq_type))
        if sub is None or len(sub) == 0:
            continue
        times = sub["time_exchange_us"].values.astype(np.int64)
        usd   = sub["usd"].values
        for i in np.where(mask)[0]:
            fi   = fire_us_arr[i]
            lo   = fi - window_s * 1_000_000
            i_lo = np.searchsorted(times, lo, side="left")
            i_hi = np.searchsorted(times, fi, side="right")
            vals[i] = usd[i_lo:i_hi].sum()
    return vals

# Precompute all (liq_type, window) combinations
liq_cols = {}
for lt in ["LONG", "SHORT"]:
    for ws in WINDOWS:
        key = (lt, ws)
        print(f"  Computing {lt} {ws}s...", flush=True)
        liq_cols[key] = compute_usd_col(lt, ws)

# ─── 3. Evaluate gates ────────────────────────────────────────────────────────
print("Evaluating gates...", flush=True)

results = []

def eval_gate(liq_type, window_s, threshold, asset_filter=None):
    key = (liq_type, window_s)
    usd_vals = liq_cols[key]

    if asset_filter is not None:
        asset_mask = (asset_arr == asset_filter)
    else:
        asset_mask = np.ones(len(sample), dtype=bool)

    # Direction alignment: SHORT cascade predicts UP, LONG cascade predicts DOWN
    if liq_type == "SHORT":
        dir_mask = (dir_arr == "Up")
    else:
        dir_mask = (dir_arr == "Down")

    gate_mask = (usd_vals >= threshold) & asset_mask & dir_mask
    n_gate = gate_mask.sum()
    if n_gate == 0:
        return None
    wr_true = won_arr[gate_mask].mean()

    # Baseline for matching direction + asset slice
    base_mask = asset_mask & dir_mask
    wr_base = won_arr[base_mask].mean() if base_mask.sum() > 0 else BASELINE_WR

    lift = wr_true - wr_base
    return {
        "liq_type": liq_type,
        "window_s": window_s,
        "threshold_usd": threshold,
        "asset": asset_filter if asset_filter else "ALL",
        "n_gate": int(n_gate),
        "n_base": int(base_mask.sum()),
        "wr_base": round(wr_base, 4),
        "wr_true": round(wr_true, 4),
        "lift_pp": round(lift * 100, 2),
    }

# All-asset gates
for ws in WINDOWS:
    for thresh in SHORT_THRESHOLDS:
        r = eval_gate("SHORT", ws, thresh, asset_filter=None)
        if r: results.append(r)
    for thresh in LONG_THRESHOLDS:
        r = eval_gate("LONG", ws, thresh, asset_filter=None)
        if r: results.append(r)

# Asset-split gates
for asset in ["BTC", "ETH", "SOL"]:
    for ws in WINDOWS:
        for thresh in SHORT_THRESHOLDS:
            r = eval_gate("SHORT", ws, thresh, asset_filter=asset)
            if r: results.append(r)
        for thresh in LONG_THRESHOLDS:
            r = eval_gate("LONG", ws, thresh, asset_filter=asset)
            if r: results.append(r)

df = pd.DataFrame(results)
print(f"\nTotal configs evaluated: {len(df)}", flush=True)

# ─── 4. Filter & report ───────────────────────────────────────────────────────
passing = df[(df["n_gate"] >= 50) & (df["lift_pp"] >= 5.0)].sort_values("lift_pp", ascending=False)
print(f"Configs passing n>=50 & lift>=+5pp: {len(passing)}", flush=True)

OUT = Path("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/reports")
OUT.mkdir(exist_ok=True)
df.to_csv(OUT / "hl_gates_refinement_full_sweep.csv", index=False)
passing.to_csv(OUT / "hl_gates_refinement_passing.csv", index=False)

print("\n=== TOP 20 by lift (all) ===")
print(df.sort_values("lift_pp", ascending=False).head(20).to_string(index=False))
print("\n=== PASSING configs (n>=50, lift>=+5pp) ===")
print(passing.to_string(index=False))

elapsed = time.time() - t0
print(f"\nDone in {elapsed:.1f}s", flush=True)
