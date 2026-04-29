"""
Robustness-audit the top 3 leveraged portfolio candidates:
  * P3_calmar_opt    — all 3 sleeves at risk=0.06, cap=5
  * P3_invvol        — baseline sleeves, inverse-vol-weighted blend (w=500)
  * P5_global_def    — sleeves w/ BTC defensive global regime gate

Runs per_year + block_bootstrap_ci + walk_forward_efficiency (permutation
skipped — heavy; reserved for final deploy report). Applies the same 8-gate
verdict as the baseline audit.

Outputs: docs/research/phase5_results/leverage_audit_<name>.json
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.run_leverage_study import (
    SLEEVE_SPECS, PORTFOLIOS, sleeve_data, OUT, BPY,
)
from strategy_lab.run_leverage_study_v2 import simulate_lev  # audit-matched
from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import atr
from strategy_lab.eval.robustness import (
    per_year_stats, block_bootstrap_ci, walk_forward_efficiency,
)

# ---------- build curves for each candidate ----------
def build_p3_calmar_opt():
    """All 3 sleeves at risk=0.06, cap=5.0"""
    sleeves = PORTFOLIOS["P3"]
    curves = {}
    for s in sleeves:
        df, le, se = sleeve_data(s)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.06, leverage_cap=5.0)
        curves[s] = eq
    return curves

def build_p5_calmar_opt():
    sleeves = PORTFOLIOS["P5"]
    curves = {}
    for s in sleeves:
        df, le, se = sleeve_data(s)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.06, leverage_cap=5.0)
        curves[s] = eq
    return curves

def build_p7_calmar_opt():
    sleeves = PORTFOLIOS["P7"]
    curves = {}
    for s in sleeves:
        df, le, se = sleeve_data(s)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.06, leverage_cap=5.0)
        curves[s] = eq
    return curves

def build_p3_invvol(window=500):
    sleeves = PORTFOLIOS["P3"]
    curves = {}
    for s in sleeves:
        df, le, se = sleeve_data(s)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
        curves[s] = eq
    return curves  # blending done separately

def build_p5_btc_defensive():
    btc = load_data("BTCUSDT", "4h", start="2021-01-01", end="2026-03-31")
    close = btc["close"]
    ema200 = close.ewm(span=200, adjust=False).mean()
    ema50  = close.ewm(span=50, adjust=False).mean()
    trend_any = ((close > ema200) & (ema50 > ema200)) | ((close < ema200) & (ema50 < ema200))
    a = pd.Series(atr(btc), index=btc.index)
    vol_rank = (a/close).rolling(500, min_periods=100).rank(pct=True)
    vol_low = vol_rank < 0.5
    gmult = pd.Series(1.0, index=btc.index)
    gmult[ trend_any &  vol_low] = 1.25
    gmult[ trend_any & ~vol_low] = 0.75
    gmult[~trend_any &  vol_low] = 1.0
    gmult[~trend_any & ~vol_low] = 0.4
    sleeves = PORTFOLIOS["P5"]
    curves = {}
    for s in sleeves:
        df, le, se = sleeve_data(s)
        mult = gmult.reindex(df.index).ffill().fillna(1.0)
        _, eq = simulate_lev(df, le, se, size_mult=mult,
                             risk_per_trade=0.03, leverage_cap=5.0)
        curves[s] = eq
    return curves

# ---------- blends ----------
def eqw_blend(curves):
    idx = None
    for eq in curves.values():
        idx = eq.index if idx is None else idx.intersection(eq.index)
    rets = pd.DataFrame({k: curves[k].reindex(idx).pct_change().fillna(0)
                         for k in curves})
    port_rets = rets.mean(axis=1)
    return (1 + port_rets).cumprod() * 10_000.0

def invvol_blend(curves, window=500):
    idx = None
    for eq in curves.values():
        idx = eq.index if idx is None else idx.intersection(eq.index)
    rets = pd.DataFrame({k: curves[k].reindex(idx).pct_change().fillna(0)
                         for k in curves})
    vol = rets.rolling(window, min_periods=max(20, window//4)).std()
    inv_vol = 1.0 / vol.replace(0, np.nan)
    weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(1.0 / len(curves))
    port_rets = (rets * weights).sum(axis=1)
    return (1 + port_rets).cumprod() * 10_000.0

# ---------- 8-gate verdict ----------
def verdict_8gate(eq, trades_dummy=None):
    rets = eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd>0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25*86400)
    total = float(eq.iloc[-1]/eq.iloc[0]-1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd!=0 else 0

    py = per_year_stats(eq, BPY)
    pos = sum(1 for d in py.values() if d["return"] > 0)
    total_yrs = len(py)
    min_yr = min((d["return"] for d in py.values()), default=0)

    boot = block_bootstrap_ci(rets, n_iter=1000, bars_per_year=BPY)
    wfe = walk_forward_efficiency(eq, bars_per_year=BPY)

    # 8 gates
    sh_lo = boot["sharpe"]["ci_lo"]
    cal_lo = boot["calmar"]["ci_lo"]
    mdd_hi = boot["max_dd"]["ci_hi"]   # ci_hi here is the "less-bad" upper; ci_lo is worst-case
    mdd_worst = boot["max_dd"]["ci_lo"]

    gates = {}
    gates["per_year_all_positive"] = (pos == total_yrs, f"{pos}/{total_yrs}")
    gates["bootstrap_sharpe_lowerCI_gt_0.5"] = (sh_lo > 0.5, round(sh_lo, 3))
    gates["bootstrap_calmar_lowerCI_gt_1.0"] = (cal_lo > 1.0, round(cal_lo, 3))
    gates["bootstrap_mdd_worstCI_gt_neg30pct"] = (mdd_worst > -0.30, round(mdd_worst, 3))
    eff = wfe.get("efficiency_ratio", 0)
    pos_folds = wfe.get("n_positive_folds", 0)
    gates["walk_forward_efficiency_gt_0.5"] = (eff > 0.5, round(eff, 3))
    gates["walk_forward_ge_5of6_pos"] = (pos_folds >= 5, f"{pos_folds}/6")
    gates["permutation_p_lt_0.01"] = (None, "skipped")
    gates["plateau_drop_le_30pct"] = (None, "skipped")

    passed = sum(1 for v, _ in gates.values() if v is True)
    total_known = sum(1 for v, _ in gates.values() if v is not None)

    return {
        "sharpe": round(sh, 3), "cagr": round(cagr, 4),
        "max_dd": round(mdd, 4), "calmar": round(cal, 3),
        "min_yr": round(min_yr, 4),
        "pos_yrs": f"{pos}/{total_yrs}",
        "per_year": py,
        "bootstrap": boot,
        "walk_forward": wfe,
        "gates": {k: {"pass": v, "value": val} for k, (v, val) in gates.items()},
        "tests_passed": f"{passed}/{total_known}",
    }

# ---------- main ----------
def main():
    t0 = time.time()
    print("Warming data caches...")
    for s in SLEEVE_SPECS:
        sleeve_data(s)

    candidates = {
        "P3_calmar_opt":      lambda: eqw_blend(build_p3_calmar_opt()),
        "P5_calmar_opt":      lambda: eqw_blend(build_p5_calmar_opt()),
        "P7_calmar_opt":      lambda: eqw_blend(build_p7_calmar_opt()),
        "P3_invvol":          lambda: invvol_blend(build_p3_invvol(), window=500),
        "P5_btc_defensive":   lambda: eqw_blend(build_p5_btc_defensive()),
    }

    results = {}
    for name, fn in candidates.items():
        print(f"\n=== Auditing {name} ===")
        eq = fn()
        rep = verdict_8gate(eq)
        results[name] = rep
        print(f"  Sharpe={rep['sharpe']} CAGR={rep['cagr']} MDD={rep['max_dd']} "
              f"Calmar={rep['calmar']} min_yr={rep['min_yr']}  {rep['tests_passed']}")
        for gn, g in rep["gates"].items():
            mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
            print(f"    [{mark:4s}] {gn:38s} -> {g['value']}")

    out_path = OUT / "leverage_audit_all.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved -> {out_path}")
    print(f"Time {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
