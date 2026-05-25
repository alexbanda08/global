"""V3 mint-and-sell simulation: asymmetric one-sided posting gated by CVD slope.

V2 baseline: always posts BOTH UP-ask and DOWN-ask at $0.50+spread.
V3 logic per fill:
  - CVD_slope_30s > +cvd_thr  -> SKIP UP post (likely UP gets adversely selected),
                                 only post DOWN-ask.
  - CVD_slope_30s < -cvd_thr  -> SKIP DOWN post, only post UP-ask.
  - |CVD_slope_30s| < cvd_thr -> post BOTH (V2 baseline).
Sigma gate (optional): sigma_60s > sigma_thr  -> SKIP entire fill (no posting either side).

Per-fill V3 PnL given V2 fill record (slug, ts, ask_up, ask_dn, up_filled, dn_filled,
outcome, sum_asks):
  notional n = 2.5; fee rate = 0.07; rebate share = 0.20 (matches V2 results).

  Case A — |CVD|<cvd_thr (V3=V2 BOTH posting):
      V3 PnL = V2's pnl_hold exactly.

  Case B — CVD > +cvd_thr (V3 skips UP-ask):
      Only DOWN-ask is live.
        if dn_filled (V2): V3 sells DOWN at ad, holds UP.
            cash = n*ad; reb = n*0.014*ad*(1-ad)
            held = n if outcome=='Up' else 0
            pnl = cash + reb + held - n
        else: V3 has no fills -> pnl = 0  (NEITHER)
  Case C — CVD < -cvd_thr (V3 skips DOWN-ask): symmetric to Case B with UP-ask only.
        if up_filled (V2): V3 sells UP at au, holds DOWN.
            cash = n*au; reb = n*0.014*au*(1-au)
            held = n if outcome=='Down' else 0
            pnl = cash + reb + held - n
        else: pnl = 0

  Sigma filter: if sigma_60s > sigma_thr -> pnl = 0 (skip entire opportunity).

Outputs:
  - data/v4/canonical/_results/mint_and_sell_v3_simulation.csv (cell × cvd_thr × sigma_thr)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

OVERLAY = RES / "mint_and_sell_cvd_overlay.csv"
OUT = RES / "mint_and_sell_v3_simulation.csv"

N = 2.5
FEE_RATE = 0.07
REBATE_SHARE = 0.20
REB_K = REBATE_SHARE * FEE_RATE  # 0.014


def rebate_per_share(p: float) -> float:
    return REB_K * p * (1.0 - p)


def v3_pnl_skip_up_only(ad: float, dn_filled: bool, outcome: str) -> float:
    """V3 skips UP-post; only DOWN-ask is live. ad = ask_dn."""
    if not dn_filled:
        return 0.0
    cash = N * ad
    reb = N * rebate_per_share(ad)
    held = N if outcome == "Up" else 0.0
    return cash + reb + held - N


def v3_pnl_skip_dn_only(au: float, up_filled: bool, outcome: str) -> float:
    """V3 skips DOWN-post; only UP-ask is live."""
    if not up_filled:
        return 0.0
    cash = N * au
    reb = N * rebate_per_share(au)
    held = N if outcome == "Down" else 0.0
    return cash + reb + held - N


# ---------------- main ----------------
print("[1/6] Loading CVD overlay…")
ov = pd.read_csv(OVERLAY)
print(f"   rows: {len(ov):,}; cells: {ov.cell.unique().tolist()}")

# Span
ts_min = ov.ts.min(); ts_max = ov.ts.max()
span_days = (ts_max - ts_min) / (24*3600*1e6)
print(f"   span: {span_days:.3f} days")

print("[2/6] Loading V2 policy_compare parquets to get ask_up/ask_dn per fill…")
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
    pcs.append(pc[["cell", "slug", "ts", "ask_up", "ask_dn", "up_filled", "dn_filled", "outcome", "pnl_hold"]])
pc_all = pd.concat(pcs, ignore_index=True)
print(f"   pc_all rows: {len(pc_all):,}")

# Merge into overlay
print("[3/6] Joining CVD overlay × V2 ask prices…")
df = ov.merge(
    pc_all[["cell", "slug", "ts", "ask_up", "ask_dn"]],
    on=["cell", "slug", "ts"], how="left", validate="one_to_one"
)
missing = int(df.ask_up.isna().sum())
print(f"   joined rows: {len(df):,}; missing ask: {missing}")
if missing:
    df = df.dropna(subset=["ask_up", "ask_dn"]).reset_index(drop=True)

# Extrap factor per cell
EXTRAP = ov.groupby("cell")["extrap_factor"].first().to_dict()
print(f"   extrap factors: {EXTRAP}")

# Sanity: V2 baseline daily per cell
print("[4/6] V2 baseline daily PnL per cell:")
v2_base = df.groupby("cell").agg(
    n_sample=("slug", "count"),
    sum_pnl_sample=("pnl_hold", "sum"),
)
v2_base["extrap"] = v2_base.index.map(EXTRAP)
v2_base["sum_pnl_extrap"] = v2_base.sum_pnl_sample * v2_base.extrap
v2_base["daily_pnl"] = v2_base.sum_pnl_extrap / span_days
print(v2_base.round(2))
print(f"V2 total daily: ${v2_base.daily_pnl.sum():,.2f}")

# Per-asset CVD percentile thresholds (use |CVD_slope_30s|; 80th-95th)
print("[5/6] Sweeping cvd_thr × sigma_thr per cell…")
PCT_CVD = [0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 1.00]  # last = no gate
PCT_SIGMA = [1.00, 0.95, 0.90, 0.80, 0.67]  # last = drop bottom 67%

# precompute per-asset quantiles
ASSET_CVD = {}
ASSET_SIGMA = {}
for asset in df.asset.unique():
    s = df.loc[df.asset == asset, "cvd_slope_30s"].abs()
    sg = df.loc[df.asset == asset, "sigma_60s"]
    ASSET_CVD[asset] = {p: float(s.quantile(p)) if p < 1.0 else float("inf") for p in PCT_CVD}
    ASSET_SIGMA[asset] = {p: float(sg.quantile(p)) if p < 1.0 else float("inf") for p in PCT_SIGMA}

print("CVD |slope| quantiles per asset (selected):")
for a in ASSET_CVD:
    print(f"  {a}: 80%={ASSET_CVD[a][0.80]:.3f}  90%={ASSET_CVD[a][0.90]:.3f}  95%={ASSET_CVD[a][0.95]:.3f}")

# Precompute V3 PnL for ALL fills under "always-skip-side" reference (only if we did skip)
# We'll compute V3 PnL per (row, cvd_thr, sigma_thr) by branching:
df["v3_skip_up_pnl"] = df.apply(
    lambda r: v3_pnl_skip_up_only(r.ask_dn, bool(r.dn_filled), str(r.outcome)), axis=1
)
df["v3_skip_dn_pnl"] = df.apply(
    lambda r: v3_pnl_skip_dn_only(r.ask_up, bool(r.up_filled), str(r.outcome)), axis=1
)

# now sweep
rows = []
for cell, g in df.groupby("cell"):
    asset = g.asset.iloc[0]
    cvd_qs = ASSET_CVD[asset]
    sig_qs = ASSET_SIGMA[asset]
    v2_sum = float(g.pnl_hold.sum())
    v2_n = int(len(g))
    extrap = float(EXTRAP[cell])
    v2_daily = v2_sum * extrap / span_days

    for cvd_p, cvd_thr in cvd_qs.items():
        for sig_p, sig_thr in sig_qs.items():
            # sigma gate first
            keep_mask = g.sigma_60s <= sig_thr
            # then CVD gate
            cvd = g.cvd_slope_30s.values
            up = cvd > +cvd_thr      # SKIP UP post → use v3_skip_up_pnl
            dn = cvd < -cvd_thr      # SKIP DOWN post → use v3_skip_dn_pnl
            mid = ~(up | dn)         # post BOTH → use V2 pnl_hold
            v3_pnl = np.where(up, g.v3_skip_up_pnl.values,
                     np.where(dn, g.v3_skip_dn_pnl.values, g.pnl_hold.values))
            v3_pnl = np.where(keep_mask.values, v3_pnl, 0.0)

            v3_sum = float(v3_pnl.sum())
            v3_active = int(((v3_pnl != 0.0)).sum())  # rough activity counter
            v3_n_kept = int(keep_mask.sum())
            v3_daily = v3_sum * extrap / span_days
            improvement_dollars = v3_daily - v2_daily
            improvement_pct = (improvement_dollars / abs(v2_daily) * 100.0) if v2_daily != 0 else float("nan")

            # Breakdown by V3 regime
            n_skip_up = int(up.sum())
            n_skip_dn = int(dn.sum())
            n_both = int(mid.sum())
            n_skipped_by_sigma = int((~keep_mask).sum())

            rows.append({
                "cell": cell,
                "asset": asset,
                "cvd_pct": cvd_p,
                "cvd_thr": cvd_thr,
                "sigma_pct": sig_p,
                "sigma_thr": sig_thr if np.isfinite(sig_thr) else float("inf"),
                "v2_n": v2_n,
                "v2_sum_pnl": v2_sum,
                "v2_daily_pnl": v2_daily,
                "v3_sum_pnl": v3_sum,
                "v3_daily_pnl": v3_daily,
                "v3_n_active": v3_active,
                "v3_n_kept": v3_n_kept,
                "v3_n_skip_up": n_skip_up,
                "v3_n_skip_dn": n_skip_dn,
                "v3_n_both": n_both,
                "v3_n_skipped_sigma": n_skipped_by_sigma,
                "improvement_dollars": improvement_dollars,
                "improvement_pct": improvement_pct,
                "span_days": span_days,
                "extrap": extrap,
            })

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False)
print(f"[6/6] Wrote {OUT} (rows={len(out)})")

# Print quick per-cell best
print("\n== Best V3 (cvd_thr × sigma_thr) per cell by v3_daily_pnl ==")
best = out.sort_values("v3_daily_pnl", ascending=False).groupby("cell").head(1).sort_values("cell")
print(best[[
    "cell", "cvd_pct", "sigma_pct", "v2_daily_pnl", "v3_daily_pnl",
    "improvement_dollars", "improvement_pct",
    "v3_n_skip_up", "v3_n_skip_dn", "v3_n_both", "v3_n_skipped_sigma",
]].to_string(index=False))

# Aggregate best total
print("\n== TOTAL V3 best (sum of per-cell bests) ==")
print(f"V2 total daily: ${best.v2_daily_pnl.sum():,.2f}")
print(f"V3 total daily: ${best.v3_daily_pnl.sum():,.2f}")
print(f"Net change: ${best.improvement_dollars.sum():,.2f}/day")

# Also single (cvd, sigma) combo applied uniformly
print("\n== Best uniform (cvd_pct, sigma_pct) across all cells ==")
agg = out.groupby(["cvd_pct", "sigma_pct"]).agg(
    v3_daily_total=("v3_daily_pnl", "sum"),
    v2_daily_total=("v2_daily_pnl", "sum"),
).reset_index()
agg["improvement"] = agg.v3_daily_total - agg.v2_daily_total
agg = agg.sort_values("v3_daily_total", ascending=False)
print(agg.head(10).round(2).to_string(index=False))
