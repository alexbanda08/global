"""
Gate 7 asset-level permutation on V52 champion.
Shuffles ETH, AVAX, SOL, LINK log-returns; rebuilds whole 4-way stack.
"""
from __future__ import annotations
import sys, json, time
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
from strategy_lab.run_v41_gate7_proper import (
    shuffle_df_lr, build_sleeve_from_df, BEST_VARIANT_MAP as V41_MAP, SLEEVE_SPECS,
)
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

SYMBOLS_V52 = ["ETHUSDT", "AVAXUSDT", "SOLUSDT", "LINKUSDT"]

def build_div_eq_from_df(symbol, df, sig_fn, kw, exit_style):
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_adaptive_exit(df, le, se, rdf["label"])
    else:
        _, eq = sim_canonical(df, le, se, **EXIT_4H)
    return eq

def build_v52_from_dfs(dfs):
    # V41 champion sleeves
    v41_curves = {}
    for sleeve, variant in V41_MAP.items():
        sym = SLEEVE_SPECS[sleeve][2]
        v41_curves[sleeve] = build_sleeve_from_df(sleeve, dfs[sym], variant)
    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    champ_r = 0.6 * p3.reindex(idx).pct_change().fillna(0) + 0.4 * p5.reindex(idx).pct_change().fillna(0)

    # Diversifier sleeves
    div_specs = {
        "A": ("SOLUSDT",  sig_mfi_extreme,         dict(lower=25, upper=75), "V41"),
        "B": ("LINKUSDT", sig_volume_profile_rot,  dict(win=60, n_bins=15),   "baseline"),
        "C": ("AVAXUSDT", sig_signed_vol_div,      dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
        "D": ("ETHUSDT",  sig_mfi_extreme,         dict(lower=25, upper=75), "baseline"),
    }
    div_eqs = {k: build_div_eq_from_df(v[0], dfs[v[0]], v[1], v[2], v[3])
               for k, v in div_specs.items()}

    # Combine
    all_idx = idx
    for eq in div_eqs.values():
        all_idx = all_idx.intersection(eq.index)
    cr = champ_r.reindex(all_idx).fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_eqs.items()}
    combined = 0.6 * cr + 0.1 * drs["A"] + 0.1 * drs["B"] + 0.1 * drs["C"] + 0.1 * drs["D"]
    return (1 + combined).cumprod() * 10_000.0

def sharpe(eq):
    r = eq.pct_change().dropna()
    sd = float(r.std())
    return (float(r.mean())/sd)*np.sqrt(BPY) if sd > 0 else 0

def main():
    t0 = time.time()
    print("Loading real symbol data...")
    real_dfs = {s: load_data(s, "4h", start="2021-01-01", end="2026-03-31") for s in SYMBOLS_V52}
    real_eq = build_v52_from_dfs(real_dfs)
    real_sh = sharpe(real_eq)
    print(f"Real Sharpe = {real_sh:.3f}")

    n_perm = 30
    rng = np.random.default_rng(42)
    nulls = []
    for k in range(n_perm):
        shuffled = {s: shuffle_df_lr(real_dfs[s], rng) for s in SYMBOLS_V52}
        try:
            eq_p = build_v52_from_dfs(shuffled)
            nulls.append(sharpe(eq_p))
        except Exception as e:
            print(f"  perm {k}: {type(e).__name__}")
        if (k+1) % 5 == 0:
            print(f"  permutation {k+1}/{n_perm} done")

    arr = np.asarray(nulls)
    p_val = float((arr >= real_sh).mean())
    print(f"\nReal Sharpe    = {real_sh:.3f}")
    print(f"Null mean      = {arr.mean():.3f}")
    print(f"Null 99th%ile  = {np.quantile(arr, 0.99):.3f}")
    print(f"p-value        = {p_val:.4f}")
    print(f"GATE 7 (p<0.01): {'PASS' if p_val < 0.01 else 'FAIL'}")

    with open(OUT / "v52_champion_gate7.json", "w") as f:
        json.dump({"real_sharpe": real_sh, "null_shs": list(map(float, nulls)),
                   "null_mean": float(arr.mean()),
                   "null_99th": float(np.quantile(arr, 0.99)),
                   "p_value": p_val,
                   "pass": p_val < 0.01,
                   "n_permutations": n_perm}, f, indent=2)
    print(f"Time: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
