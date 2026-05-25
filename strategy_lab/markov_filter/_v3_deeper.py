"""Deeper V3 analysis — ablation, more extreme sigma cuts, do-nothing baseline,
   per-cell deep dive to find best params."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OVERLAY = RES / "mint_and_sell_cvd_overlay.csv"

N = 2.5
FEE_RATE = 0.07
REBATE_SHARE = 0.20
REB_K = REBATE_SHARE * FEE_RATE


def rebate_per_share(p):
    return REB_K * p * (1.0 - p)


# load
ov = pd.read_csv(OVERLAY)
span_days = (ov.ts.max() - ov.ts.min()) / (24*3600*1e6)

CELL_DIRS = {
    "btc_5m":  "mint_and_sell_v2_btc_5m_2026_05_16",
    "btc_15m": "mint_and_sell_v2_btc_15m_2026_05_16",
    "eth_5m":  "mint_and_sell_v2_eth_5m_2026_05_16",
    "eth_15m": "mint_and_sell_v2_eth_15m_2026_05_16",
    "sol_5m":  "mint_and_sell_v2_sol_5m_2026_05_16",
    "sol_15m": "mint_and_sell_v2_sol_15m_2026_05_16",
}
pcs = []
for cell, d in CELL_DIRS.items():
    p = RES / d / "policy_compare.parquet"
    pc = pd.read_parquet(p)
    pc["cell"] = cell
    pcs.append(pc[["cell", "slug", "ts", "ask_up", "ask_dn"]])
pc_all = pd.concat(pcs, ignore_index=True)

df = ov.merge(pc_all, on=["cell", "slug", "ts"], how="left").reset_index(drop=True)
EXTRAP = ov.groupby("cell")["extrap_factor"].first().to_dict()

# Compute the V3 skip-pnls
def calc_v3_skip_up(r):
    if not r.dn_filled:
        return 0.0
    ad = r.ask_dn
    return N * ad + N * rebate_per_share(ad) + (N if r.outcome == "Up" else 0.0) - N

def calc_v3_skip_dn(r):
    if not r.up_filled:
        return 0.0
    au = r.ask_up
    return N * au + N * rebate_per_share(au) + (N if r.outcome == "Down" else 0.0) - N

df["v3_skip_up_pnl"] = df.apply(calc_v3_skip_up, axis=1)
df["v3_skip_dn_pnl"] = df.apply(calc_v3_skip_dn, axis=1)

# ---------------- ABLATIONS ----------------
# 1. Pure SIGMA skip (skip if sigma_60s > p)
# 2. Pure CVD-asymmetric (no sigma skip)
# 3. Sigma+CVD combined (already in v3_simulation)
# 4. Skip-only-when-CVD-and-sigma-both-high (more conservative)
# 5. Just "always one-sided": always skip the leg with higher fill probability — naive sanity

def v3_pnl_array(g, cvd_thr=np.inf, sigma_thr=np.inf, do_sigma_skip=True, do_cvd_skip=True):
    cvd = g.cvd_slope_30s.values
    sig = g.sigma_60s.values
    if do_sigma_skip:
        keep = sig <= sigma_thr
    else:
        keep = np.ones_like(cvd, dtype=bool)
    if do_cvd_skip:
        up = cvd > +cvd_thr
        dn = cvd < -cvd_thr
        v3 = np.where(up, g.v3_skip_up_pnl.values,
              np.where(dn, g.v3_skip_dn_pnl.values, g.pnl_hold.values))
    else:
        v3 = g.pnl_hold.values
    v3 = np.where(keep, v3, 0.0)
    return v3


def evaluate_cell(g, cell, cvd_thr, sigma_thr, do_sigma=True, do_cvd=True):
    extrap = EXTRAP[cell]
    v3 = v3_pnl_array(g, cvd_thr, sigma_thr, do_sigma, do_cvd)
    sm = v3.sum()
    daily = sm * extrap / span_days
    return daily


# Per-cell percentile thresholds
def asset_q(g, col, pct):
    s = g[col].abs() if col == "cvd_slope_30s" else g[col]
    return s.quantile(pct)


print("===== ABLATION 1: PURE SIGMA SKIP (no CVD asymmetric) =====")
for pct in [0.95, 0.90, 0.80, 0.67, 0.50, 0.33, 0.20]:
    sigma_thr_per_cell = df.groupby("asset").sigma_60s.quantile(pct).to_dict()
    daily_by_cell = {}
    for cell, g in df.groupby("cell"):
        asset = g.asset.iloc[0]
        sg = sigma_thr_per_cell[asset]
        daily = evaluate_cell(g, cell, cvd_thr=np.inf, sigma_thr=sg, do_cvd=False)
        daily_by_cell[cell] = daily
    total = sum(daily_by_cell.values())
    print(f"  sigma_pct={pct:.2f}: total_daily=${total:>10,.2f}  per-cell: {daily_by_cell}")

print("\n===== ABLATION 2: PURE CVD-ASYMMETRIC SKIP (no sigma skip) =====")
for pct in [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]:
    cvd_thr_per_asset = df.groupby("asset").apply(lambda g: g.cvd_slope_30s.abs().quantile(pct)).to_dict()
    daily_by_cell = {}
    for cell, g in df.groupby("cell"):
        asset = g.asset.iloc[0]
        ct = cvd_thr_per_asset[asset]
        daily = evaluate_cell(g, cell, cvd_thr=ct, sigma_thr=np.inf, do_sigma=False)
        daily_by_cell[cell] = daily
    total = sum(daily_by_cell.values())
    print(f"  cvd_pct={pct:.2f}: total_daily=${total:>10,.2f}  per-cell: {daily_by_cell}")

print("\n===== ABLATION 3: SIGMA + CVD COMBINED (joint sweep) =====")
print("Format: row=sigma_pct, col=cvd_pct")
sigma_pcts = [1.00, 0.90, 0.80, 0.67, 0.50, 0.33]
cvd_pcts   = [1.00, 0.95, 0.90, 0.80, 0.70, 0.60, 0.50]
import io
header = "sigma\\cvd  " + "  ".join(f"{p:>8.2f}" for p in cvd_pcts)
print(header)
for sp in sigma_pcts:
    row_vals = []
    for cp in cvd_pcts:
        sigma_thr_per_asset = df.groupby("asset").sigma_60s.quantile(sp).to_dict() if sp < 1.0 else {a: np.inf for a in df.asset.unique()}
        cvd_thr_per_asset = df.groupby("asset").apply(lambda g: g.cvd_slope_30s.abs().quantile(cp)).to_dict() if cp < 1.0 else {a: np.inf for a in df.asset.unique()}
        tot = 0.0
        for cell, g in df.groupby("cell"):
            asset = g.asset.iloc[0]
            tot += evaluate_cell(g, cell, cvd_thr=cvd_thr_per_asset[asset], sigma_thr=sigma_thr_per_asset[asset])
        row_vals.append(tot)
    print(f"{sp:>8.2f}  " + "  ".join(f"{v:>+8,.0f}" for v in row_vals))

print("\n===== ABLATION 4: BREAK-EVEN ANALYSIS — find the most aggressive sigma cut =====")
for pct in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]:
    sigma_thr_per_asset = df.groupby("asset").sigma_60s.quantile(pct).to_dict()
    n_kept = 0
    n_total = 0
    daily_by_cell = {}
    for cell, g in df.groupby("cell"):
        asset = g.asset.iloc[0]
        sg = sigma_thr_per_asset[asset]
        daily = evaluate_cell(g, cell, cvd_thr=np.inf, sigma_thr=sg, do_cvd=False)
        daily_by_cell[cell] = daily
        n_kept += int((g.sigma_60s <= sg).sum())
        n_total += len(g)
    total = sum(daily_by_cell.values())
    pct_kept = 100.0 * n_kept / n_total
    print(f"  sigma_pct={pct:.2f} (keep ~{pct_kept:.1f}%): total_daily=${total:>10,.2f}")

print("\n===== ABLATION 5: Combined sigma_p ∈ {.30, .40, .50} × cvd_p ∈ {.50, .60} =====")
for sp in [0.30, 0.40, 0.50, 0.67]:
    for cp in [0.50, 0.60, 0.70]:
        sigma_thr_per_asset = df.groupby("asset").sigma_60s.quantile(sp).to_dict()
        cvd_thr_per_asset = df.groupby("asset").apply(lambda g: g.cvd_slope_30s.abs().quantile(cp)).to_dict()
        tot = 0.0
        for cell, g in df.groupby("cell"):
            asset = g.asset.iloc[0]
            tot += evaluate_cell(g, cell, cvd_thr=cvd_thr_per_asset[asset], sigma_thr=sigma_thr_per_asset[asset])
        print(f"  sigma_p={sp:.2f}, cvd_p={cp:.2f}: total_daily=${tot:>10,.2f}")

# Statistical sanity: is the CVD signal monotonic — bigger cuts help more?
print("\n===== SANITY CHECK: BOTH-fill rows only — does sigma still correlate w/ PnL? =====")
both = df[df.maker_side == "BOTH"]
print(f"  BOTH-fills: n={len(both):,}, mean_pnl=${both.pnl_hold.mean():.4f}, sum_pnl=${both.pnl_hold.sum():.2f}")
for asset, gg in both.groupby("asset"):
    q67 = gg.sigma_60s.quantile(0.67)
    lo = gg[gg.sigma_60s <= q67]
    hi = gg[gg.sigma_60s > q67]
    print(f"  {asset}: sigma<=p67 (n={len(lo)}) mean=${lo.pnl_hold.mean():.4f}, hi (n={len(hi)}) mean=${hi.pnl_hold.mean():.4f}")

print("\n===== SANITY: HELD-side losses dominated by which sigma bin? =====")
held = df[df.maker_side.isin(["UP", "DOWN"])]
print(f"  HELD fills: n={len(held):,}, mean_pnl=${held.pnl_hold.mean():.4f}")
for asset, gg in held.groupby("asset"):
    q67 = gg.sigma_60s.quantile(0.67)
    lo = gg[gg.sigma_60s <= q67]
    hi = gg[gg.sigma_60s > q67]
    print(f"  {asset}: sigma<=p67 (n={len(lo)}) mean=${lo.pnl_hold.mean():.4f}, hi (n={len(hi)}) mean=${hi.pnl_hold.mean():.4f}")
