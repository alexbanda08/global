"""
V52 — Multi-diversifier stacking on the champion.
Takes the top V51 diversifier sleeves and tests 2-way and 3-way combinations.

Diversifier sleeves (low corr with champion, positive Sharpe):
  A = SOL_MFI_75_25_V41           (best single-layer Sharpe)
  B = LINK_VP_ROT_60_baseline     (best single-layer Calmar)
  C = AVAX_SVD_tight_baseline     (best SVD_DIV variant)
  D = ETH_MFI_75_25_baseline      (best ETH MFI)
  E = ETH_VP_ROT_60_baseline      (positive on ETH)
  F = ETH_MFI_70_30_V41

Test combinations:
  2-way: {A,B,C,D} paired at various weights
  3-way: {A+B+C}, {A+B+D}, {A+C+D}, {B+C+D}
  4-way: all four
"""
from __future__ import annotations
import sys, time, json
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
from strategy_lab.run_v41_expansion import metrics
from strategy_lab.run_v41_gates import build_sleeve_curve, BEST_VARIANT_MAP
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

# Diversifier specs
DIVERSIFIERS = {
    "A_SOL_MFI75_V41":   ("SOLUSDT",  sig_mfi_extreme,       dict(lower=25, upper=75), "V41"),
    "B_LINK_VPROT60_bl": ("LINKUSDT", sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
    "C_AVAX_SVD_bl":     ("AVAXUSDT", sig_signed_vol_div,    dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
    "D_ETH_MFI75_bl":    ("ETHUSDT",  sig_mfi_extreme,       dict(lower=25, upper=75), "baseline"),
    "E_ETH_VPROT60_bl":  ("ETHUSDT",  sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
    "F_ETH_MFI70_V41":   ("ETHUSDT",  sig_mfi_extreme,       dict(lower=30, upper=70), "V41"),
}

def build_div(coin, sig_fn, kw, exit_style):
    df = load_data(coin, "4h", start="2021-01-01", end="2026-03-31")
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_adaptive_exit(df, le, se, rdf["label"])
    else:
        _, eq = sim_canonical(df, le, se, **EXIT_4H)
    return eq

def main():
    t0 = time.time()
    print("Building champion + diversifier curves...")
    # Champion
    base_curves = {s: build_sleeve_curve(s, v) for s, v in BEST_VARIANT_MAP.items()}
    p3_eq = invvol_blend({k: base_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5_eq = eqw_blend({k: base_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3_eq.index.intersection(p5_eq.index)
    champ_r = 0.6 * p3_eq.reindex(idx).pct_change().fillna(0) + 0.4 * p5_eq.reindex(idx).pct_change().fillna(0)
    champ_eq = (1 + champ_r).cumprod() * 10_000.0
    mc = metrics(champ_eq, [])
    print(f"Champion: Sharpe={mc['sharpe']} CAGR={mc['cagr']*100:+.1f}% "
          f"MDD={mc['mdd']*100:+.1f}% Cal={mc['calmar']}")

    # Diversifiers
    div_eqs = {}
    for name, (coin, sfn, kw, ex) in DIVERSIFIERS.items():
        print(f"  Building {name}...")
        div_eqs[name] = build_div(coin, sfn, kw, ex)

    # Align all to common index
    all_idx = champ_eq.index
    for eq in div_eqs.values():
        all_idx = all_idx.intersection(eq.index)
    cr = champ_eq.reindex(all_idx).pct_change().fillna(0)
    div_r = {n: eq.reindex(all_idx).pct_change().fillna(0) for n, eq in div_eqs.items()}

    # --- Correlation matrix among diversifiers ---
    print("\nDiversifier correlations with champion and each other:")
    corr_df = pd.DataFrame({"champ": cr, **div_r}).corr()
    print(corr_df.round(3).to_string())

    # --- Test single, 2-way, 3-way, 4-way stacks ---
    def blend_test(champion_w: float, div_weights: dict):
        total_w = champion_w + sum(div_weights.values())
        if abs(total_w - 1.0) > 1e-6: return None
        blended = champion_w * cr
        for n, w in div_weights.items():
            blended = blended + w * div_r[n]
        eq = (1 + blended).cumprod() * 10_000.0
        return eq, metrics(eq, [])

    results = []
    # single-layer (already tested in V51 — skip; retest top 3 here too for consistency)
    print("\n--- Single-layer (recap) ---")
    for name in ["A_SOL_MFI75_V41", "B_LINK_VPROT60_bl", "C_AVAX_SVD_bl", "D_ETH_MFI75_bl"]:
        for w in [0.15, 0.20]:
            _, m = blend_test(1.0 - w, {name: w})
            print(f"  champ@{1-w:.0%} + {name}@{w:.0%}: Sh={m['sharpe']:.3f} "
                  f"CAGR={m['cagr']*100:+5.1f}% MDD={m['mdd']*100:+6.1f}% Cal={m['calmar']:.2f} "
                  f"minYr={m['min_yr']*100:+5.1f}% pos={m['pos_yrs']}/6")
            results.append({"config": f"single_{name}_{w}",
                             "sharpe": m["sharpe"], "cagr": m["cagr"],
                             "mdd": m["mdd"], "calmar": m["calmar"],
                             "min_yr": m["min_yr"], "pos_yrs": m["pos_yrs"]})

    # 2-way stacks
    print("\n--- 2-way stacks (champ@70% + two diversifiers@15% each) ---")
    pairs = [("A","B"),("A","C"),("A","D"),("B","C"),("B","D"),("C","D"),
              ("A","E"),("B","E"),("A","F")]
    for a,b in pairs:
        na = next(k for k in DIVERSIFIERS if k.startswith(a+"_"))
        nb = next(k for k in DIVERSIFIERS if k.startswith(b+"_"))
        for wa, wb in [(0.15, 0.15), (0.10, 0.10), (0.20, 0.10), (0.10, 0.20)]:
            eq_m = blend_test(1 - wa - wb, {na: wa, nb: wb})
            if eq_m is None: continue
            _, m = eq_m
            better = m["sharpe"] > mc["sharpe"] and m["calmar"] > mc["calmar"]
            flag = "WIN" if better else ("SH+" if m["sharpe"] > mc["sharpe"] else "")
            print(f"  [{flag:3s}] champ@{1-wa-wb:.0%} + {a}@{wa:.0%} + {b}@{wb:.0%}: "
                  f"Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+5.1f}% MDD={m['mdd']*100:+6.1f}% "
                  f"Cal={m['calmar']:.2f} minYr={m['min_yr']*100:+5.1f}%")
            results.append({"config": f"2way_{a}_{b}_{wa}_{wb}",
                             "sharpe": m["sharpe"], "cagr": m["cagr"],
                             "mdd": m["mdd"], "calmar": m["calmar"],
                             "min_yr": m["min_yr"], "pos_yrs": m["pos_yrs"]})

    # 3-way stacks
    print("\n--- 3-way stacks (champ@55% + three@15% each) ---")
    triples = [("A","B","C"), ("A","B","D"), ("A","C","D"), ("B","C","D"),
                ("A","B","E"), ("A","D","E")]
    for a,b,c in triples:
        na = next(k for k in DIVERSIFIERS if k.startswith(a+"_"))
        nb = next(k for k in DIVERSIFIERS if k.startswith(b+"_"))
        nc = next(k for k in DIVERSIFIERS if k.startswith(c+"_"))
        for each_w in [0.10, 0.15]:
            champ_w = 1 - 3*each_w
            if champ_w < 0.4: continue
            eq_m = blend_test(champ_w, {na: each_w, nb: each_w, nc: each_w})
            if eq_m is None: continue
            _, m = eq_m
            better = m["sharpe"] > mc["sharpe"] and m["calmar"] > mc["calmar"]
            flag = "WIN" if better else ("SH+" if m["sharpe"] > mc["sharpe"] else "")
            print(f"  [{flag:3s}] champ@{champ_w:.0%} + {a},{b},{c}@{each_w:.0%} each: "
                  f"Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+5.1f}% MDD={m['mdd']*100:+6.1f}% "
                  f"Cal={m['calmar']:.2f} minYr={m['min_yr']*100:+5.1f}%")
            results.append({"config": f"3way_{a}{b}{c}_{each_w}",
                             "sharpe": m["sharpe"], "cagr": m["cagr"],
                             "mdd": m["mdd"], "calmar": m["calmar"],
                             "min_yr": m["min_yr"], "pos_yrs": m["pos_yrs"]})

    # 4-way stack
    print("\n--- 4-way stack (champ@40-50% + four diversifiers) ---")
    for each_w in [0.10, 0.125, 0.15]:
        champ_w = 1 - 4*each_w
        if champ_w < 0.4: continue
        eq_m = blend_test(champ_w, {"A_SOL_MFI75_V41": each_w,
                                      "B_LINK_VPROT60_bl": each_w,
                                      "C_AVAX_SVD_bl": each_w,
                                      "D_ETH_MFI75_bl": each_w})
        if eq_m is None: continue
        _, m = eq_m
        better = m["sharpe"] > mc["sharpe"] and m["calmar"] > mc["calmar"]
        flag = "WIN" if better else ""
        print(f"  [{flag:3s}] champ@{champ_w:.0%} + ABCD@{each_w:.1%} each: "
              f"Sh={m['sharpe']:.3f} CAGR={m['cagr']*100:+5.1f}% MDD={m['mdd']*100:+6.1f}% "
              f"Cal={m['calmar']:.2f} minYr={m['min_yr']*100:+5.1f}%")
        results.append({"config": f"4way_ABCD_{each_w}",
                         "sharpe": m["sharpe"], "cagr": m["cagr"],
                         "mdd": m["mdd"], "calmar": m["calmar"],
                         "min_yr": m["min_yr"], "pos_yrs": m["pos_yrs"]})

    # sort and show top 10
    print("\n" + "=" * 90)
    print("TOP 10 OVERALL by Sharpe")
    print("=" * 90)
    sorted_res = sorted(results, key=lambda x: x["sharpe"], reverse=True)
    for r in sorted_res[:10]:
        print(f"  {r['config']:40s}  Sh={r['sharpe']:.3f}  CAGR={r['cagr']*100:+5.1f}%  "
              f"MDD={r['mdd']*100:+5.1f}%  Cal={r['calmar']:.2f}  minYr={r['min_yr']*100:+5.1f}%")

    with open(OUT / "v52_multistack_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nTime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
