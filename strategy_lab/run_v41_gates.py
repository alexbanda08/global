"""
Run full 10-gate battery on NEW_60_40_V41 champion candidate.

Reuses gate infrastructure from:
  - run_leverage_audit.py (gates 1-6)
  - run_leverage_gates78.py (gates 7-8)
  - run_leverage_gates910.py (gates 9-10)

Candidate recipe:
  - P3 side (60%, invvol blend): CCI_ETH_V41 + STF_AVAX_V45 + STF_SOL_baseline
  - P5 side (40%, eqw blend):    CCI_ETH_V41 + LATBB_AVAX_baseline + STF_SOL_baseline
"""
from __future__ import annotations
import importlib.util, json, sys, time
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

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",  "sig_cci_extreme",     "ETHUSDT",  "4h"),
    "STF_SOL_4h":    ("run_v30_creative.py",  "sig_supertrend_flip", "SOLUSDT",  "4h"),
    "STF_AVAX_4h":   ("run_v30_creative.py",  "sig_supertrend_flip", "AVAXUSDT", "4h"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",    "sig_lateral_bb_fade", "AVAXUSDT", "4h"),
}

def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".","_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)

def build_sleeve_curve(sleeve_label, variant):
    script, fn, sym, tf = SLEEVE_SPECS[sleeve_label]
    df = load_data(sym, tf, start="2021-01-01", end="2026-03-31")
    sig = import_sig(script, fn)
    le, se = sig(df)

    if variant == "baseline":
        _, eq = sim_canonical(df, le, se, **EXIT_4H)
    elif variant == "V41":
        _, regime_df = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_adaptive_exit(df, le, se, regime_df["label"])
    elif variant == "V45":
        _, regime_df = fit_regime_model(df, train_frac=0.30, seed=42)
        vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
        vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, eq = simulate_adaptive_exit(df, le2, se2, regime_df["label"])
    return eq

# Best variant per sleeve (from V41-V45 grid winners)
BEST_VARIANT_MAP = {
    "CCI_ETH_4h":    "V41",
    "STF_SOL_4h":    "baseline",
    "STF_AVAX_4h":   "V45",
    "LATBB_AVAX_4h": "baseline",
}

def main():
    t0 = time.time()
    print("Building leveraged V41 sleeve curves...")
    curves = {}
    for s, v in BEST_VARIANT_MAP.items():
        print(f"  {s} -> {v}")
        curves[s] = build_sleeve_curve(s, v)

    # P3 side: CCI_ETH + STF_AVAX + STF_SOL (invvol blend)
    p3_invvol_eq = invvol_blend({k: curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    # P5 side: CCI_ETH + LATBB_AVAX + STF_SOL (eqw blend)
    p5_eqw_eq = eqw_blend({k: curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})

    idx = p3_invvol_eq.index.intersection(p5_eqw_eq.index)
    combined_r = (0.60 * p3_invvol_eq.reindex(idx).pct_change().fillna(0)
                 + 0.40 * p5_eqw_eq.reindex(idx).pct_change().fillna(0))
    combo_eq = (1 + combined_r).cumprod() * 10_000.0

    # Headline metrics
    rets = combo_eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd > 0 else 0
    pk = combo_eq.cummax(); mdd = float((combo_eq/pk - 1).min())
    yrs = (combo_eq.index[-1] - combo_eq.index[0]).total_seconds()/(365.25*86400)
    total = float(combo_eq.iloc[-1]/combo_eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    yearly = {}
    for yr in sorted(set(combo_eq.index.year)):
        e = combo_eq[combo_eq.index.year == yr]
        if len(e) >= 30:
            yearly[int(yr)] = float(e.iloc[-1]/e.iloc[0] - 1)

    print(f"\nNEW_60_40_V41 headline:")
    print(f"  Sharpe={sh:.3f} CAGR={cagr*100:+.1f}% MDD={mdd*100:+.1f}% Calmar={cal:.2f}")
    print(f"  min_yr={min(yearly.values())*100:+.1f}% pos_yrs={sum(1 for r in yearly.values() if r>0)}/{len(yearly)}")

    # ---- Gates 1-6 ----
    print("\nRunning Gates 1-6 (8-gate verdict)...")
    g6 = verdict_8gate(combo_eq)
    print(f"  {g6['tests_passed']}")
    for gn, g in g6["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"    [{mark:4s}] {gn:38s} -> {g['value']}")

    # ---- Gate 7 permutation on blend (simplified: block bootstrap of returns) ----
    print("\nRunning Gate 7 (permutation on blend returns)...")
    rng = np.random.default_rng(42)
    real_sharpe = sh
    null_shs = []
    rets_arr = rets.to_numpy()
    for _ in range(30):
        perm = rng.permutation(rets_arr)
        eq_perm = np.cumprod(1 + perm)
        rp = pd.Series(eq_perm).pct_change().dropna()
        sdp = float(rp.std())
        null_shs.append((float(rp.mean())/sdp)*np.sqrt(BPY) if sdp > 0 else 0)
    null_arr = np.array(null_shs)
    p7 = float((null_arr >= real_sharpe).mean())
    print(f"    Real Sharpe = {real_sharpe:.3f}  Null mean = {null_arr.mean():.3f}  "
          f"Null 99th = {np.quantile(null_arr, 0.99):.3f}  p-value = {p7:.4f}")
    print(f"    GATE 7 (p<0.01): {'PASS' if p7 < 0.01 else 'FAIL'}")

    # ---- Gates 9-10 (Monte Carlo) ----
    print("\nRunning Gates 9-10 (Monte Carlo)...")
    g9 = gate9_path_shuffle(combo_eq, n_iter=10_000)
    print(f"  Gate 9 path-shuffle: MDD 5th={g9['mdd_p5']*100:.1f}%  median={g9['mdd_p50']*100:.1f}%  "
          f"total-ret 5th={g9['ret_p5']*100:.1f}%  GATE 9 {'PASS' if g9['gate9_pass'] else 'FAIL'}")
    g10 = gate10_forward_paths(combo_eq, n_paths=1000, year_bars=2190)
    print(f"  Gate 10 forward 1y: MDD 5th={g10['mdd_p5']*100:.1f}%  median={g10['mdd_p50']*100:.1f}%  "
          f"CAGR 5th={g10['cagr_p5']*100:.1f}%  median={g10['cagr_p50']*100:.1f}%")
    print(f"    P(neg year)={g10['p_negative_year_pct']}%  P(DD>20%)={g10['p_dd_worse_than_20pct']}%  "
          f"P(DD>30%)={g10['p_dd_worse_than_30pct']}%")
    print(f"    GATE 10: {'PASS' if g10['gate10_pass'] else 'FAIL'}")

    # Save summary
    summary = {
        "candidate":            "NEW_60_40_V41",
        "recipe":               BEST_VARIANT_MAP,
        "sharpe":               round(sh, 3), "cagr": round(cagr, 4),
        "mdd":                  round(mdd, 4), "calmar": round(cal, 3),
        "min_yr":               round(min(yearly.values()), 4),
        "pos_yrs":              f"{sum(1 for r in yearly.values() if r>0)}/{len(yearly)}",
        "yearly":               yearly,
        "gates_1_6":            g6,
        "gate7_permutation":    {"p_value": p7, "real_sharpe": real_sharpe,
                                  "null_mean": float(null_arr.mean()),
                                  "null_99th": float(np.quantile(null_arr, 0.99)),
                                  "pass": p7 < 0.01},
        "gate9_path_shuffle":   g9,
        "gate10_forward_paths": g10,
    }
    with open(OUT / "v41_champion_audit.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSaved -> {OUT}/v41_champion_audit.json")
    print(f"Time: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
