"""
V41 expansion stage 2 — multi-layer stacking and proper sleeve integration.

Discoveries from stage 1:
  SOL_VWZ_V47   : diversifier — blend Sharpe 2.416 -> 2.442 at 75/25
  DOGE_LATBB_V47: Calmar diversifier — 3.80 -> 3.87 at 85/15

But standalone both have pos_yrs < 4/6 — diversification only.

Stage 2 tests:
  A) 3-way stack: champion + SOL_VWZ_V47 + DOGE_LATBB_V47
  B) Add SOL_VWZ_V47 as a real 4th sleeve in P3 side (5-sleeve P3)
  C) Weight-grid search over the 3-way stack
"""
from __future__ import annotations
import importlib.util, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import simulate as sim_canonical
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend
from strategy_lab.run_v41_expansion import simulate_v47_breakeven, metrics
from strategy_lab.run_v41_gates import build_sleeve_curve, BEST_VARIANT_MAP

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".","_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)

def build_sol_vwz_v47():
    df = load_data("SOLUSDT", "4h", start="2021-01-01", end="2026-03-31")
    sig = import_sig("run_v30_creative.py", "sig_vwap_zfade")
    out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
    _, eq = simulate_v47_breakeven(df, le, se)
    return eq

def build_doge_latbb_v47():
    df = load_data("DOGEUSDT", "4h", start="2021-01-01", end="2026-03-31")
    sig = import_sig("run_v29_regime.py", "sig_lateral_bb_fade")
    out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
    _, eq = simulate_v47_breakeven(df, le, se)
    return eq

def main():
    t0 = time.time()
    print("Building base sleeves...")
    base_curves = {s: build_sleeve_curve(s, v) for s, v in BEST_VARIANT_MAP.items()}
    sol_vwz = build_sol_vwz_v47()
    doge_latbb = build_doge_latbb_v47()
    print("  Done.")

    # Baseline champion
    p3_eq = invvol_blend({k: base_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5_eq = eqw_blend({k: base_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3_eq.index.intersection(p5_eq.index)
    champ_r = 0.6 * p3_eq.reindex(idx).pct_change().fillna(0) + 0.4 * p5_eq.reindex(idx).pct_change().fillna(0)
    champ_eq = (1 + champ_r).cumprod() * 10_000.0
    mc = metrics(champ_eq, [], "champion")
    print(f"\nChampion: Sharpe={mc['sharpe']} CAGR={mc['cagr']*100:+.1f}% "
          f"MDD={mc['mdd']*100:+.1f}% Cal={mc['calmar']} minYr={mc['min_yr']*100:+.1f}%")

    # -------- Test A: 3-way stack (grid over (w_sol, w_doge)) --------
    print("\n--- A) 3-way stack: champion + SOL_VWZ_V47 + DOGE_LATBB_V47 ---")
    idx_all = champ_eq.index.intersection(sol_vwz.index).intersection(doge_latbb.index)
    cr = champ_eq.reindex(idx_all).pct_change().fillna(0)
    sr = sol_vwz.reindex(idx_all).pct_change().fillna(0)
    dr = doge_latbb.reindex(idx_all).pct_change().fillna(0)

    best_a = None
    for w_sol in [0.10, 0.15, 0.20, 0.25]:
        for w_doge in [0.05, 0.10, 0.15]:
            w_champ = 1 - w_sol - w_doge
            if w_champ < 0.5: continue
            blended = w_champ * cr + w_sol * sr + w_doge * dr
            eq = (1 + blended).cumprod() * 10_000.0
            m = metrics(eq, [], f"stack_{w_champ:.2f}_{w_sol:.2f}_{w_doge:.2f}")
            winner = m["sharpe"] > mc["sharpe"]
            calmar_better = m["calmar"] > mc["calmar"]
            mark = "WIN" if winner else ("CAL" if calmar_better else "   ")
            print(f"  [{mark}] champ@{w_champ:.0%} SOL@{w_sol:.0%} DOGE@{w_doge:.0%}: "
                  f"Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+.1f}% MDD={m['mdd']*100:+.1f}% "
                  f"Cal={m['calmar']:.2f} minYr={m['min_yr']*100:+.1f}%")
            if winner and (best_a is None or m["sharpe"] > best_a[1]["sharpe"]):
                best_a = ((w_champ, w_sol, w_doge), m, eq)

    if best_a:
        print(f"\n  BEST-A: weights={best_a[0]}  Sharpe={best_a[1]['sharpe']} "
              f"CAGR={best_a[1]['cagr']*100:+.1f}% Cal={best_a[1]['calmar']}")

    # -------- Test B: SOL_VWZ_V47 as 4th sleeve in P3 side --------
    print("\n--- B) 4-sleeve P3 (add SOL_VWZ_V47) ---")
    p3b_curves = {
        "CCI_ETH_4h": base_curves["CCI_ETH_4h"],
        "STF_AVAX_4h": base_curves["STF_AVAX_4h"],
        "STF_SOL_4h": base_curves["STF_SOL_4h"],
        "SOL_VWZ_V47": sol_vwz,
    }
    p3b_invvol = invvol_blend(p3b_curves, window=500)
    p3b_eqw = eqw_blend(p3b_curves)

    for variant_name, p3_variant in [("P3_4sleeve_invvol", p3b_invvol),
                                        ("P3_4sleeve_eqw", p3b_eqw)]:
        idx_b = p3_variant.index.intersection(p5_eq.index)
        r = 0.6 * p3_variant.reindex(idx_b).pct_change().fillna(0) + 0.4 * p5_eq.reindex(idx_b).pct_change().fillna(0)
        eq_b = (1 + r).cumprod() * 10_000.0
        m = metrics(eq_b, [], variant_name)
        winner = m["sharpe"] > mc["sharpe"]
        mark = "WIN" if winner else "   "
        print(f"  [{mark}] {variant_name:24s} Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+.1f}% "
              f"MDD={m['mdd']*100:+.1f}% Cal={m['calmar']:.2f} minYr={m['min_yr']*100:+.1f}%")

    # -------- Test C: add BOTH as 4th sleeves --------
    print("\n--- C) 5-sleeve P3 + 4-sleeve P5 (add BOTH) ---")
    p3c_curves = {**p3b_curves, "DOGE_LATBB_V47": doge_latbb}
    p3c_invvol = invvol_blend(p3c_curves, window=500)
    p3c_eqw = eqw_blend(p3c_curves)

    p5c_curves = {k: base_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]}
    p5c_curves["DOGE_LATBB_V47"] = doge_latbb
    p5c_eq = eqw_blend(p5c_curves)

    for variant_name, p3_variant, p5_variant in [
        ("P3_5sl_invvol + P5_3sl", p3c_invvol, p5_eq),
        ("P3_5sl_invvol + P5_4sl", p3c_invvol, p5c_eq),
        ("P3_5sl_eqw    + P5_4sl", p3c_eqw, p5c_eq),
    ]:
        idx_c = p3_variant.index.intersection(p5_variant.index)
        r = 0.6 * p3_variant.reindex(idx_c).pct_change().fillna(0) + 0.4 * p5_variant.reindex(idx_c).pct_change().fillna(0)
        eq_c = (1 + r).cumprod() * 10_000.0
        m = metrics(eq_c, [], variant_name)
        winner = m["sharpe"] > mc["sharpe"]
        mark = "WIN" if winner else "   "
        print(f"  [{mark}] {variant_name:28s} Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+.1f}% "
              f"MDD={m['mdd']*100:+.1f}% Cal={m['calmar']:.2f} minYr={m['min_yr']*100:+.1f}%")

    print(f"\nTime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
