"""
At the H_refined anchor=300 candidate, add a CVD confirmation gate.
Hypothesis: when H signal AND polymarket trade-flow CVD agree, hit rate improves.

Output: dataset showing H+CVD joint signal vs H-only.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_trades

DIR = Path(__file__).parent

# Load the candidate H_refined results
frames = [pd.read_parquet(f) for f in sorted(DIR.glob("refine_H_*_anchor*.parquet"))]
df = pd.concat(frames, ignore_index=True)

# Filter to the candidate cell: 15m anchor=300, horizon=600, BTC+ETH, vwap 0.3-0.7, thr=0.08
sel = (df.tf=="15m") & (df.anchor_off_s==300) & (df.horizon_s==600) & (df.asset != "SOL") & (df.vwap > 0.3) & (df.vwap < 0.7) & (df.thr == 0.08)
cand = df[sel].copy()
cand["slot_start"] = cand.slug.str.rsplit("-", n=1).str[1].astype("int64")
cand["slot_start_us"] = cand.slot_start * 1_000_000
cand["entry_us"] = cand.slot_start_us + 600 * 1_000_000   # anchor=300 → entry = slot_start + 600s for 15m
print(f"H_refined candidate trades: {len(cand)}")

# For each asset, load trades once, then for each trade compute CVD
# CVD over [entry_us - 300s, entry_us] on Up-side: BUY=+size, SELL=-size
cand["cvd_up_5min"] = np.nan
cand["cvd_down_5min"] = np.nan

for asset in ["BTC", "ETH"]:
    asub = cand[cand.asset == asset]
    if len(asub) == 0: continue
    tr = load_trades(asset.lower())
    tr = tr.copy()
    tr["side_upper"] = tr.side.str.upper()
    # Pre-sort by slug + ts for fast group lookups
    tr = tr.sort_values(["slug","outcome","timestamp_us"]).reset_index(drop=True)

    # For efficiency, group by slug once
    by_slug_out = {}
    for (slug, oc), g in tr.groupby(["slug","outcome"]):
        by_slug_out[(slug, oc)] = (g.timestamp_us.values, g["size"].values.astype(float), g.side_upper.values)

    cvd_up_list = []
    cvd_dn_list = []
    idx_list = []
    for idx, row in asub.iterrows():
        slug = row.slug
        entry_us = int(row.entry_us)
        lo = entry_us - 300 * 1_000_000
        cvd_up = 0.0
        cvd_dn = 0.0
        # Up-side
        key_u = (slug, "Up")
        if key_u in by_slug_out:
            ts, sz, sd = by_slug_out[key_u]
            mask = (ts >= lo) & (ts < entry_us)
            if mask.any():
                signs = np.where(sd[mask] == "BUY", 1.0, -1.0)
                cvd_up = float((sz[mask] * signs).sum())
        key_d = (slug, "Down")
        if key_d in by_slug_out:
            ts, sz, sd = by_slug_out[key_d]
            mask = (ts >= lo) & (ts < entry_us)
            if mask.any():
                signs = np.where(sd[mask] == "BUY", 1.0, -1.0)
                cvd_dn = float((sz[mask] * signs).sum())
        cvd_up_list.append(cvd_up)
        cvd_dn_list.append(cvd_dn)
        idx_list.append(idx)
    cand.loc[idx_list, "cvd_up_5min"] = cvd_up_list
    cand.loc[idx_list, "cvd_down_5min"] = cvd_dn_list

# CVD "directional": positive UP-side CVD means buy-pressure on UP shares
# Match with H signal: H says UP and CVD-up > 0 → confirmation
cand["cvd_agrees"] = np.where(
    cand.signal == "UP",  cand.cvd_up_5min > 0,
    np.where(cand.signal == "DOWN", cand.cvd_down_5min > 0, False)
)
cand["cvd_strong_agrees"] = np.where(
    cand.signal == "UP",  cand.cvd_up_5min > 100,
    np.where(cand.signal == "DOWN", cand.cvd_down_5min > 100, False)
)

# Save
cand.to_parquet(DIR / "refine_H_cvd_filter.parquet", index=False)

# Results
np.random.seed(42)

def perm_p(pnl_vals):
    n = len(pnl_vals)
    if n == 0: return 1.0
    pnls = []
    for _ in range(1000):
        flips = np.random.choice([1,-1], size=n)
        pnls.append((pnl_vals * flips).sum())
    return (np.array(pnls) >= pnl_vals.sum()).mean()

print()
print("=== Without CVD filter (baseline) ===")
print(f"  n={len(cand)}  hit={cand.won.mean():.4f}  pnl=${cand.pnl.sum():+.0f}  ppt=${cand.pnl.mean():+.2f}  p={perm_p(cand.pnl.values):.3f}")

print()
print("=== With CVD agree (cvd_signal > 0) ===")
agr = cand[cand.cvd_agrees]
print(f"  n={len(agr)}  hit={agr.won.mean():.4f}  pnl=${agr.pnl.sum():+.0f}  ppt=${agr.pnl.mean():+.2f}  p={perm_p(agr.pnl.values):.3f}")

print()
print("=== With CVD strong-agree (cvd_signal > 100) ===")
sagr = cand[cand.cvd_strong_agrees]
print(f"  n={len(sagr)}  hit={sagr.won.mean():.4f}  pnl=${sagr.pnl.sum():+.0f}  ppt=${sagr.pnl.mean():+.2f}  p={perm_p(sagr.pnl.values):.3f}")

print()
print("=== CVD disagrees (signal contradicts trade flow) ===")
dis = cand[~cand.cvd_agrees]
print(f"  n={len(dis)}  hit={dis.won.mean():.4f}  pnl=${dis.pnl.sum():+.0f}  ppt=${dis.pnl.mean():+.2f}  p={perm_p(dis.pnl.values):.3f}")
