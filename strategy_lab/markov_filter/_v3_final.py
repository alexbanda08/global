"""V3 final analysis — per-cell best params + ultra-aggressive combos + n-warnings."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OVERLAY = RES / "mint_and_sell_cvd_overlay.csv"

N = 2.5
REB_K = 0.014


def rebate_per_share(p):
    return REB_K * p * (1.0 - p)


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


def calc_v3_skip_up(r):
    if not r.dn_filled: return 0.0
    ad = r.ask_dn
    return N*ad + N*rebate_per_share(ad) + (N if r.outcome=="Up" else 0.0) - N

def calc_v3_skip_dn(r):
    if not r.up_filled: return 0.0
    au = r.ask_up
    return N*au + N*rebate_per_share(au) + (N if r.outcome=="Down" else 0.0) - N

df["v3_skip_up_pnl"] = df.apply(calc_v3_skip_up, axis=1)
df["v3_skip_dn_pnl"] = df.apply(calc_v3_skip_dn, axis=1)

def v3_pnl_array(g, cvd_thr=np.inf, sigma_thr=np.inf):
    cvd = g.cvd_slope_30s.values
    sig = g.sigma_60s.values
    keep = sig <= sigma_thr
    up = cvd > +cvd_thr; dn = cvd < -cvd_thr
    v3 = np.where(up, g.v3_skip_up_pnl.values, np.where(dn, g.v3_skip_dn_pnl.values, g.pnl_hold.values))
    v3 = np.where(keep, v3, 0.0)
    return v3

# 1. PER-CELL best with full grid
print("===== PER-CELL OPTIMAL V3 PARAMS =====")
rows = []
SIGMA_PCTS = [1.00, 0.95, 0.90, 0.80, 0.67, 0.50, 0.33, 0.25, 0.20, 0.15, 0.10]
CVD_PCTS = [1.00, 0.95, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30]

for cell, g in df.groupby("cell"):
    asset = g.asset.iloc[0]
    extrap = EXTRAP[cell]
    v2_daily = float(g.pnl_hold.sum() * extrap / span_days)
    best = None
    for sp in SIGMA_PCTS:
        st = float(g.sigma_60s.quantile(sp)) if sp < 1.0 else np.inf
        for cp in CVD_PCTS:
            ct = float(g.cvd_slope_30s.abs().quantile(cp)) if cp < 1.0 else np.inf
            v3 = v3_pnl_array(g, ct, st)
            v3_daily = float(v3.sum() * extrap / span_days)
            n_kept = int((v3 != 0.0).sum())
            n_active_frac = n_kept / len(g)
            if best is None or v3_daily > best[2]:
                best = (sp, cp, v3_daily, n_kept, n_active_frac, st, ct)
    sp, cp, v3d, nk, nf, st, ct = best
    print(f"  {cell}: V2=${v2_daily:>+7,.0f}  V3=${v3d:>+7,.0f}  imp=${v3d-v2_daily:>+7,.0f}  "
          f"sigma_p={sp:.2f}(thr={st:.2e}) cvd_p={cp:.2f}(thr={ct:.3f}) n_active={nk}({100*nf:.0f}%)")
    rows.append({
        "cell": cell, "asset": asset, "v2_daily": v2_daily, "v3_daily": v3d,
        "improvement": v3d - v2_daily, "sigma_pct": sp, "cvd_pct": cp,
        "sigma_thr": st, "cvd_thr": ct, "n_active": nk, "n_fraction": nf,
        "v2_sample_n": len(g),
    })

bs = pd.DataFrame(rows)
print(f"\nTOTAL: V2=${bs.v2_daily.sum():,.2f}/day, V3=${bs.v3_daily.sum():,.2f}/day, "
      f"improvement=${bs.improvement.sum():,.2f}/day "
      f"({100*bs.improvement.sum()/abs(bs.v2_daily.sum()):.1f}%)")

# 2. CVD-conditional pnl per leg: does CVD signal actually work?
print("\n===== CVD CONDITIONAL: Per-leg V3 PnL by CVD sign (sanity) =====")
# For each fill, ask: if we WOULD skip UP because CVD>0, what's V3 PnL? compare to V2 PnL on those rows.
for asset in df.asset.unique():
    sub = df[df.asset == asset]
    qhi = sub.cvd_slope_30s.abs().quantile(0.50)
    high_pos = sub[sub.cvd_slope_30s > +qhi]
    high_neg = sub[sub.cvd_slope_30s < -qhi]
    print(f"\n  {asset} (cvd>+p50={qhi:.3f}, n={len(high_pos)}, V2 mean_pnl=${high_pos.pnl_hold.mean():.4f}):")
    if len(high_pos) > 0:
        v3_alt = high_pos.v3_skip_up_pnl.mean()
        print(f"    V3 alt (skip UP, keep DN): mean V3 PnL=${v3_alt:.4f}  "
              f"diff vs V2=${v3_alt - high_pos.pnl_hold.mean():+.4f}")
    print(f"  {asset} (cvd<-p50, n={len(high_neg)}, V2 mean_pnl=${high_neg.pnl_hold.mean():.4f}):")
    if len(high_neg) > 0:
        v3_alt = high_neg.v3_skip_dn_pnl.mean()
        print(f"    V3 alt (skip DN, keep UP): mean V3 PnL=${v3_alt:.4f}  "
              f"diff vs V2=${v3_alt - high_neg.pnl_hold.mean():+.4f}")

# 3. Best uniform global
print("\n===== BEST UNIFORM GLOBAL (cvd_pct, sigma_pct) =====")
def global_eval(cp, sp):
    tot = 0.0
    for cell, g in df.groupby("cell"):
        asset = g.asset.iloc[0]
        sg = float(g.sigma_60s.quantile(sp)) if sp < 1.0 else np.inf
        ct = float(g.cvd_slope_30s.abs().quantile(cp)) if cp < 1.0 else np.inf
        v3 = v3_pnl_array(g, ct, sg)
        tot += float(v3.sum() * EXTRAP[cell] / span_days)
    return tot

print(f"{'cvd_pct':>8s} {'sigma_pct':>10s} {'total_daily':>14s}")
for cp in [1.00, 0.95, 0.80, 0.60, 0.50, 0.40, 0.30]:
    for sp in [1.00, 0.80, 0.50, 0.33, 0.20, 0.10]:
        v = global_eval(cp, sp)
        print(f"{cp:>8.2f} {sp:>10.2f} ${v:>+12,.0f}")

# 4. Sample size warnings — per bucket counts
print("\n===== PER-CELL N WARNINGS at best configs =====")
for r in rows:
    cell, sp, cp = r["cell"], r["sigma_pct"], r["cvd_pct"]
    g = df[df.cell == cell]
    sg = float(g.sigma_60s.quantile(sp)) if sp < 1.0 else np.inf
    ct = float(g.cvd_slope_30s.abs().quantile(cp)) if cp < 1.0 else np.inf
    keep = g.sigma_60s <= sg
    up_skip = (g.cvd_slope_30s > +ct) & keep
    dn_skip = (g.cvd_slope_30s < -ct) & keep
    both = ~(up_skip | dn_skip) & keep
    print(f"  {cell}: n_kept={keep.sum()}, n_skipUP={up_skip.sum()}, n_skipDN={dn_skip.sum()}, n_BOTH={both.sum()}, "
          f"n_sigmaDropped={(~keep).sum()}")
