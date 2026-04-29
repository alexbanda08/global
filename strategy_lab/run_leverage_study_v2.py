"""
LEVERAGE STUDY v2 — smarter approaches
======================================
v1 revealed that naive per-sleeve leverage boosts HURT blend Sharpe even when
they help per-sleeve Sharpe (correlated-DD amplification). v2 tests portfolio-
aware approaches:

  Exp 7   Baseline sanity check — reproduce P3/P5/P7 Sharpes from report
  Exp 8   Asymmetric sizing      — anchor at 1x, diversifier at 1.5x/2x/3x
  Exp 9   Global regime gate     — BTC vol / trend drives portfolio-wide mult
  Exp 10  Inverse-vol weighting  — scale sleeve weight = 1/rolling_sigma
  Exp 11  Best per-sleeve risk   — pick best static risk per sleeve, then blend

Output: docs/research/phase5_results/leverage_v2_*.csv + json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Reuse helpers from v1
from strategy_lab.run_leverage_study import (
    SLEEVE_SPECS, PORTFOLIOS, sleeve_data, simulate_lev as _raw_simulate_lev,
    compute_regimes, metrics, blend_daily, blend_metrics, OUT, BPY,
)
from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import atr

# Audit-matched exit stack (run_portfolio_audit.py uses this — NOT canonical defaults)
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

def simulate_lev(df, long_entries, short_entries=None, **kw):
    """Wrapper that injects audit-matched exit params unless overridden."""
    for k, v in EXIT_4H.items():
        kw.setdefault(k, v)
    return _raw_simulate_lev(df, long_entries, short_entries, **kw)

# ---------------------------------------------------------------- Exp 7
def exp7_baseline_sanity():
    """Reproduce baseline P3/P5/P7 blends with canonical 3%/3x sim."""
    print("\n=== EXP 7: Baseline blend sanity check ===")
    baseline_curves = {}
    for lbl in SLEEVE_SPECS:
        df, le, se = sleeve_data(lbl)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
        baseline_curves[lbl] = eq
    results = {}
    for pname, sleeves in PORTFOLIOS.items():
        curves = {s: baseline_curves[s] for s in sleeves}
        results[pname] = blend_metrics(curves, pname)
    for pname, m in results.items():
        print(f"  {pname}  Sharpe={m['sharpe']} CAGR={m['cagr']} "
              f"MDD={m['mdd']} Calmar={m['calmar']} min_yr={m['min_yr']}")
    with open(OUT / "leverage_v2_baseline.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    return results, baseline_curves

# ---------------------------------------------------------------- Exp 8
def exp8_asymmetric(baseline_curves):
    """Anchor at 1x, boost diversifiers. CCI_ETH is universal anchor."""
    print("\n=== EXP 8: Asymmetric sizing (anchor fixed, diversifier scaled) ===")
    ANCHOR = "CCI_ETH_4h"
    # boost_factors applied to non-anchor sleeves via risk_per_trade
    boosts = [1.0, 1.25, 1.5, 2.0]   # 1x/1.25x/1.5x/2x risk for non-anchors
    rows = []
    for pname, sleeves in PORTFOLIOS.items():
        for b in boosts:
            curves = {}
            for s in sleeves:
                df, le, se = sleeve_data(s)
                r = 0.03 if s == ANCHOR else 0.03 * b
                cap = 3.0 if s == ANCHOR else 5.0
                _, eq = simulate_lev(df, le, se, risk_per_trade=r, leverage_cap=cap)
                curves[s] = eq
            m = blend_metrics(curves, f"{pname}_x{b}")
            m.update({"portfolio": pname, "boost": b})
            rows.append(m)
        best = max([x for x in rows if x["portfolio"] == pname],
                   key=lambda x: x["sharpe"])
        print(f"  {pname:4s} best@x{best['boost']}  Sharpe={best['sharpe']} "
              f"CAGR={best['cagr']} MDD={best['mdd']} Calmar={best['calmar']} "
              f"min_yr={best['min_yr']}")
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_v2_exp8_asymmetric.csv", index=False)
    return df_out

# ---------------------------------------------------------------- Exp 9
def exp9_global_regime():
    """
    Global BTC regime gate: use BTC 4h data to classify trend/vol state,
    apply that as a size multiplier across ALL sleeves uniformly.
    """
    print("\n=== EXP 9: Global BTC regime gate ===")
    btc = load_data("BTCUSDT", "4h", start="2021-01-01", end="2026-03-31")
    # Global regime
    close = btc["close"]
    ema200 = close.ewm(span=200, adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    trend_up   = (close > ema200) & (ema50 > ema200)
    trend_dn   = (close < ema200) & (ema50 < ema200)
    trend_any  = trend_up | trend_dn
    a = pd.Series(atr(btc), index=btc.index)
    vol_ratio = a / close
    vol_rank = vol_ratio.rolling(500, min_periods=100).rank(pct=True)
    vol_low = vol_rank < 0.5

    variants = {
        "trend_x_vol":  {"TT_V-": 2.0, "TT_V+": 1.25, "T-_V-": 1.0,  "T-_V+": 0.5},
        "defensive":    {"TT_V-": 1.25,"TT_V+": 0.75, "T-_V-": 1.0,  "T-_V+": 0.4},
        "aggressive":   {"TT_V-": 3.0, "TT_V+": 1.5,  "T-_V-": 1.25, "T-_V+": 0.5},
        "trend_boost":  {"TT_V-": 2.0, "TT_V+": 2.0,  "T-_V-": 0.75, "T-_V+": 0.75},
        "vol_boost":    {"TT_V-": 1.75,"TT_V+": 0.75, "T-_V-": 1.75, "T-_V+": 0.75},
    }

    rows = []
    for vname, mults in variants.items():
        # build global multiplier series on BTC index
        gmult = pd.Series(1.0, index=btc.index)
        gmult[ trend_any &  vol_low] = mults["TT_V-"]
        gmult[ trend_any & ~vol_low] = mults["TT_V+"]
        gmult[~trend_any &  vol_low] = mults["T-_V-"]
        gmult[~trend_any & ~vol_low] = mults["T-_V+"]
        # build curves with global gate
        curves_by_sleeve = {}
        for lbl in SLEEVE_SPECS:
            df, le, se = sleeve_data(lbl)
            mult = gmult.reindex(df.index).ffill().fillna(1.0)
            _, eq = simulate_lev(df, le, se, size_mult=mult,
                                 risk_per_trade=0.03, leverage_cap=5.0)
            curves_by_sleeve[lbl] = eq
        # blend each portfolio
        for pname, sleeves in PORTFOLIOS.items():
            m = blend_metrics({s: curves_by_sleeve[s] for s in sleeves}, f"{pname}_{vname}")
            m.update({"portfolio": pname, "variant": vname})
            rows.append(m)
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_v2_exp9_global_regime.csv", index=False)
    # print best per portfolio
    for pname in PORTFOLIOS:
        best = max([x for x in rows if x["portfolio"] == pname],
                   key=lambda x: x["sharpe"])
        print(f"  {pname:4s} best={best['variant']:12s}  "
              f"Sharpe={best['sharpe']} CAGR={best['cagr']} "
              f"MDD={best['mdd']} Calmar={best['calmar']}")
    return df_out

# ---------------------------------------------------------------- Exp 10
def exp10_inverse_vol(baseline_curves):
    """Inverse-vol weighting: scale each sleeve's allocation inversely to its
    rolling volatility."""
    print("\n=== EXP 10: Inverse-vol weighted blending ===")
    rows = []
    for pname, sleeves in PORTFOLIOS.items():
        # compute rolling vol of each sleeve returns
        idx = None
        for s in sleeves:
            eq = baseline_curves[s]
            idx = eq.index if idx is None else idx.intersection(eq.index)
        rets = pd.DataFrame({s: baseline_curves[s].reindex(idx).pct_change().fillna(0)
                             for s in sleeves})
        # rolling vol 120 bars (~20 days of 4h)
        for window in [60, 120, 250, 500]:
            vol = rets.rolling(window, min_periods=max(20, window//4)).std()
            inv_vol = 1.0 / vol.replace(0, np.nan)
            weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(1.0 / len(sleeves))
            port_rets = (rets * weights).sum(axis=1)
            eq = (1.0 + port_rets).cumprod() * 10_000.0
            rs = eq.pct_change().dropna()
            mu, sd = float(rs.mean()), float(rs.std())
            sh = (mu/sd)*np.sqrt(BPY) if sd>0 else 0
            pk = eq.cummax(); mdd = float((eq/pk - 1).min())
            yrs = (eq.index[-1]-eq.index[0]).total_seconds()/(365.25*86400)
            total = float(eq.iloc[-1]/eq.iloc[0]-1)
            cagr = (1+total)**(1/max(yrs,1e-6))-1
            cal = cagr/abs(mdd) if mdd!=0 else 0
            yrs_pos = []
            for yr in sorted(set(eq.index.year)):
                e = eq[eq.index.year == yr]
                if len(e) >= 30:
                    yrs_pos.append(float(e.iloc[-1]/e.iloc[0]-1))
            rows.append({"portfolio": pname, "window": window,
                "sharpe": round(sh,2), "cagr": round(cagr,3),
                "mdd": round(mdd,3), "calmar": round(cal,2),
                "min_yr": round(min(yrs_pos),3) if yrs_pos else 0,
                "pos_yrs": sum(1 for r in yrs_pos if r > 0)})
        best = max([x for x in rows if x["portfolio"] == pname], key=lambda x: x["sharpe"])
        print(f"  {pname:4s} best@w={best['window']}  Sharpe={best['sharpe']} "
              f"CAGR={best['cagr']} MDD={best['mdd']} Calmar={best['calmar']}")
    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "leverage_v2_exp10_invvol.csv", index=False)
    return df_out

# ---------------------------------------------------------------- Exp 11
def exp11_per_sleeve_static():
    """
    Sweep risk_per_trade per sleeve, pick the SHARPE-maximizing config,
    then blend with those per-sleeve custom configs.
    Unlike v1's blind 'best-overall', also try: max Calmar-optimizing config.
    """
    print("\n=== EXP 11: Per-sleeve best-static -> blend ===")
    risks = [0.02, 0.025, 0.03, 0.035, 0.04, 0.05, 0.06]
    # search best per sleeve by (a) sharpe, (b) calmar
    per_sleeve_best = {}
    for lbl in SLEEVE_SPECS:
        df, le, se = sleeve_data(lbl)
        cand = []
        for r in risks:
            t, eq = simulate_lev(df, le, se, risk_per_trade=r, leverage_cap=5.0)
            m = metrics(eq, t, lbl); m["risk"] = r; m["eq"] = eq
            cand.append(m)
        best_sh = max(cand, key=lambda x: x["sharpe"])
        best_ca = max(cand, key=lambda x: x["calmar"])
        per_sleeve_best[lbl] = {"sharpe_opt": best_sh, "calmar_opt": best_ca}
        print(f"  {lbl:14s} sh_opt: r={best_sh['risk']} Sh={best_sh['sharpe']} Ca={best_sh['calmar']}  "
              f"| ca_opt: r={best_ca['risk']} Sh={best_ca['sharpe']} Ca={best_ca['calmar']}")

    # Build blends using sharpe-opt configs and calmar-opt configs
    for mode in ("sharpe_opt", "calmar_opt"):
        print(f"\n  --- {mode} blends ---")
        for pname, sleeves in PORTFOLIOS.items():
            curves = {s: per_sleeve_best[s][mode]["eq"] for s in sleeves}
            m = blend_metrics(curves, f"{pname}_{mode}")
            print(f"    {pname}_{mode:12s}  Sharpe={m['sharpe']} CAGR={m['cagr']} "
                  f"MDD={m['mdd']} Calmar={m['calmar']} min_yr={m['min_yr']}")
    # store
    export = {lbl: {k: {kk: vv for kk, vv in v.items() if kk != "eq"}
                    for k, v in d.items()}
              for lbl, d in per_sleeve_best.items()}
    with open(OUT / "leverage_v2_exp11_sleeve_opt.json", "w") as f:
        json.dump(export, f, indent=2, default=str)
    return per_sleeve_best

# ---------------------------------------------------------------- MAIN
def main():
    t0 = time.time()
    print("Warming caches...")
    for lbl in SLEEVE_SPECS:
        sleeve_data(lbl)

    baseline, baseline_curves = exp7_baseline_sanity()
    e8  = exp8_asymmetric(baseline_curves)
    e9  = exp9_global_regime()
    e10 = exp10_inverse_vol(baseline_curves)
    e11 = exp11_per_sleeve_static()

    print("\n" + "=" * 70)
    print("LEVERAGE STUDY v2 SUMMARY")
    print("=" * 70)
    print("\nBaseline (canonical 3%/3x):")
    for p in ["P3", "P5", "P7"]:
        m = baseline[p]
        print(f"  {p}  Sharpe={m['sharpe']} CAGR={m['cagr']} MDD={m['mdd']} "
              f"Calmar={m['calmar']} min_yr={m['min_yr']}")
    print(f"\nTime {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
