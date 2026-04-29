"""
Full 10-gate battery on V52 CHAMPION candidate:
  0.60 * NEW_60_40_V41 + 0.10 * A + 0.10 * B + 0.10 * C + 0.10 * D

Runs gates 1-6 (standard audit), gate 7 (asset-level permutation),
gate 9 (path-shuffle MC), gate 10 (forward 1y MC).
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import simulate as sim_canonical, atr
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend, verdict_8gate
from strategy_lab.run_leverage_gates910 import gate9_path_shuffle, gate10_forward_paths
from strategy_lab.run_v41_gates import build_sleeve_curve, BEST_VARIANT_MAP
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

DIVERSIFIERS = {
    "A_SOL_MFI75_V41":   ("SOLUSDT",  sig_mfi_extreme,       dict(lower=25, upper=75), "V41"),
    "B_LINK_VPROT60_bl": ("LINKUSDT", sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
    "C_AVAX_SVD_bl":     ("AVAXUSDT", sig_signed_vol_div,    dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
    "D_ETH_MFI75_bl":    ("ETHUSDT",  sig_mfi_extreme,       dict(lower=25, upper=75), "baseline"),
}

def build_div_eq(coin, sig_fn, kw, exit_style):
    df = load_data(coin, "4h", start="2021-01-01", end="2026-03-31")
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_adaptive_exit(df, le, se, rdf["label"])
    else:
        _, eq = sim_canonical(df, le, se, **EXIT_4H)
    return eq

def build_v52_champion():
    # V41 champion as the base
    base_curves = {s: build_sleeve_curve(s, v) for s, v in BEST_VARIANT_MAP.items()}
    p3_eq = invvol_blend({k: base_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5_eq = eqw_blend({k: base_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3_eq.index.intersection(p5_eq.index)
    champ_r = 0.6 * p3_eq.reindex(idx).pct_change().fillna(0) + 0.4 * p5_eq.reindex(idx).pct_change().fillna(0)
    champ_eq = (1 + champ_r).cumprod() * 10_000.0

    # Diversifiers
    div_eqs = {n: build_div_eq(coin, sfn, kw, ex) for n, (coin, sfn, kw, ex) in DIVERSIFIERS.items()}
    all_idx = champ_eq.index
    for eq in div_eqs.values():
        all_idx = all_idx.intersection(eq.index)
    cr = champ_eq.reindex(all_idx).pct_change().fillna(0)
    div_r = {n: eq.reindex(all_idx).pct_change().fillna(0) for n, eq in div_eqs.items()}

    # Combined @ 60/10/10/10/10
    combined = 0.60 * cr + 0.10*div_r["A_SOL_MFI75_V41"] + 0.10*div_r["B_LINK_VPROT60_bl"] \
             + 0.10*div_r["C_AVAX_SVD_bl"] + 0.10*div_r["D_ETH_MFI75_bl"]
    v52_eq = (1 + combined).cumprod() * 10_000.0
    return v52_eq, champ_eq, div_eqs

def main():
    t0 = time.time()
    print("Building V52 champion (4-way stack)...")
    v52_eq, champ_eq, div_eqs = build_v52_champion()

    # Headline metrics
    rets = v52_eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd > 0 else 0
    pk = v52_eq.cummax(); mdd = float((v52_eq/pk - 1).min())
    yrs = (v52_eq.index[-1] - v52_eq.index[0]).total_seconds()/(365.25*86400)
    total = float(v52_eq.iloc[-1]/v52_eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    yearly = {}
    for yr in sorted(set(v52_eq.index.year)):
        e = v52_eq[v52_eq.index.year == yr]
        if len(e) >= 30:
            yearly[int(yr)] = float(e.iloc[-1]/e.iloc[0] - 1)

    print(f"V52 champion headline:")
    print(f"  Sharpe={sh:.3f} CAGR={cagr*100:+.1f}% MDD={mdd*100:+.1f}% Calmar={cal:.2f}")
    print(f"  min_yr={min(yearly.values())*100:+.1f}%  pos_yrs={sum(1 for r in yearly.values() if r>0)}/{len(yearly)}")

    # ---- Gates 1-6 via standard audit ----
    print("\nRunning Gates 1-6...")
    g6 = verdict_8gate(v52_eq)
    print(f"  {g6['tests_passed']}")
    for gn, g in g6["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"    [{mark:4s}] {gn:38s} -> {g['value']}")

    # ---- Gate 9 path-shuffle ----
    print("\nGate 9 path-shuffle (n=10000)...")
    g9 = gate9_path_shuffle(v52_eq, n_iter=10_000)
    print(f"  MDD 5th={g9['mdd_p5']*100:.1f}%  median={g9['mdd_p50']*100:.1f}%")
    print(f"  Total-ret 5th={g9['ret_p5']*100:.1f}%  median={g9['ret_p50']*100:.1f}%")
    print(f"  GATE 9: {'PASS' if g9['gate9_pass'] else 'FAIL'}")

    # ---- Gate 10 forward 1y ----
    print("\nGate 10 forward 1y (n=1000)...")
    g10 = gate10_forward_paths(v52_eq, n_paths=1000, year_bars=2190)
    print(f"  MDD 5th={g10['mdd_p5']*100:.1f}%  median={g10['mdd_p50']*100:.1f}%")
    print(f"  CAGR 5th={g10['cagr_p5']*100:.1f}%  median={g10['cagr_p50']*100:.1f}%")
    print(f"  P(neg year)={g10['p_negative_year_pct']}%  P(DD>20%)={g10['p_dd_worse_than_20pct']}%")
    print(f"  GATE 10: {'PASS' if g10['gate10_pass'] else 'FAIL'}")

    # ---- Summary ----
    summary = {
        "candidate": "V52_CHAMPION_4WAY",
        "recipe": {
            "NEW_60_40_V41": 0.60,
            "SOL_MFI75_V41": 0.10,
            "LINK_VP_ROT60_baseline": 0.10,
            "AVAX_SVD_baseline": 0.10,
            "ETH_MFI75_baseline": 0.10,
        },
        "sharpe": round(sh, 3), "cagr": round(cagr, 4),
        "mdd": round(mdd, 4), "calmar": round(cal, 3),
        "min_yr": round(min(yearly.values()), 4),
        "yearly": yearly,
        "gates_1_6": g6,
        "gate9_path_shuffle": g9,
        "gate10_forward_paths": g10,
    }
    with open(OUT / "v52_champion_audit.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSaved -> {OUT}/v52_champion_audit.json")
    print(f"Time: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
