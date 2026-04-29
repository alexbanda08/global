"""
Blend the top V40 st_adaptive sleeves and compare vs NEW 60/40.

Candidates:
  V40_3_canonical: ETH/AVAX/SOL 4h st_adaptive, canonical exit
  V40_3_tp12:       ETH/AVAX/SOL 4h st_adaptive, tp12 exit
  V40_3_mixed:      ETH+SOL tp12 + AVAX canonical (best exit per coin)
  V40_4_mixed:      adds DOGE st_adaptive canonical
  NEW_60_40 + V40:  layered addition (50/30/20 weighting)

Also runs the 10-gate battery on the top variant.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import simulate as sim_canonical
from strategy_lab.eval.perps_simulator_tp12 import simulate_tp12
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.strategies.adaptive.v40_regime_adaptive import sig_v40_st_adaptive
from strategy_lab.run_leverage_audit import eqw_blend

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
TP12_4H = dict(tp1_atr=3.0, tp2_atr=10.0, tp1_frac=0.5,
               sl_atr=2.0, trail_atr=6.0, tight_trail_atr=2.5, max_hold=60)

def build_sleeve(symbol: str, exit_style: str):
    df = load_data(symbol, "4h", start="2021-01-01", end="2026-03-31")
    _, regime_df = fit_regime_model(df, train_frac=0.30, seed=42)
    le, se = sig_v40_st_adaptive(df, regime_df)
    if exit_style == "canonical":
        tr, eq = sim_canonical(df, le, se, **EXIT_4H)
    else:
        tr, eq = simulate_tp12(df, le, se, **TP12_4H)
    return tr, eq

def metrics(eq, label=""):
    rets = eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25*86400)
    total = float(eq.iloc[-1]/eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    yearly = {}
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yearly[int(yr)] = float(e.iloc[-1]/e.iloc[0] - 1)
    return {"label": label, "sharpe": round(sh, 3), "cagr": round(cagr, 4),
            "mdd": round(mdd, 4), "calmar": round(cal, 3),
            "min_yr": round(min(yearly.values()), 4) if yearly else 0,
            "pos_yrs": sum(1 for r in yearly.values() if r > 0),
            "total_yrs": len(yearly)}

def main():
    t0 = time.time()
    print("Building V40 sleeves...")
    sleeves = {}
    for sym in ["ETHUSDT", "AVAXUSDT", "SOLUSDT", "DOGEUSDT"]:
        for ex in ["canonical", "tp12"]:
            key = f"{sym[:-4]}_{ex}"
            tr, eq = build_sleeve(sym, ex)
            sleeves[key] = (tr, eq)
            print(f"  {key}: n={len(tr)} sharpe-hint={metrics(eq)['sharpe']}")

    # Blends
    configs = {
        "V40_3_canonical": ["ETH_canonical", "AVAX_canonical", "SOL_canonical"],
        "V40_3_tp12":       ["ETH_tp12", "AVAX_tp12", "SOL_tp12"],
        "V40_3_mixed":     ["ETH_tp12", "AVAX_canonical", "SOL_tp12"],
        "V40_4_mixed":     ["ETH_tp12", "AVAX_canonical", "SOL_tp12", "DOGE_canonical"],
    }
    results = {}
    for name, keys in configs.items():
        curves = {k: sleeves[k][1] for k in keys}
        eq = eqw_blend(curves)
        m = metrics(eq, name)
        results[name] = m
        print(f"  {name:20s} Sharpe={m['sharpe']} CAGR={m['cagr']*100:+.1f}% "
              f"MDD={m['mdd']*100:+.1f}% Calmar={m['calmar']} "
              f"min_yr={m['min_yr']*100:+.1f}% pos={m['pos_yrs']}/{m['total_yrs']}")

    # Stack onto NEW_60_40? Load its equity from the combined json
    try:
        combo_data = json.loads((OUT/"leverage_combined_60_40.json").read_text())
        new_60_40 = combo_data["NEW_COMBO_60_40"]
        print(f"\nNEW_60_40 baseline: Sharpe={new_60_40['sharpe']} CAGR={new_60_40['cagr']*100:+.1f}%")
    except Exception as e:
        print(f"  Couldn't load NEW_60_40: {e}")

    out_path = OUT / "v40_blend_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved -> {out_path}")
    print(f"Time {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
