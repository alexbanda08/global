"""
Proper asset-level permutation for NEW_60_40_V41.
Shuffles each underlying symbol's OHLC, re-runs sleeves (V41/V45/baseline per
the recipe), re-blends, compares Sharpe. This is the same methodology as
run_leverage_gates78.py's Gate 7.
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

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",  "sig_cci_extreme",     "ETHUSDT",  "4h"),
    "STF_SOL_4h":    ("run_v30_creative.py",  "sig_supertrend_flip", "SOLUSDT",  "4h"),
    "STF_AVAX_4h":   ("run_v30_creative.py",  "sig_supertrend_flip", "AVAXUSDT", "4h"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",    "sig_lateral_bb_fade", "AVAXUSDT", "4h"),
}
BEST_VARIANT_MAP = {
    "CCI_ETH_4h":    "V41",
    "STF_SOL_4h":    "baseline",
    "STF_AVAX_4h":   "V45",
    "LATBB_AVAX_4h": "baseline",
}
SYMBOLS = sorted({spec[2] for spec in SLEEVE_SPECS.values()})  # AVAX, ETH, SOL

def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".","_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)

def shuffle_df_lr(df, rng):
    close = df["close"].to_numpy()
    log_r = np.diff(np.log(close))
    perm = rng.permutation(log_r)
    new_close = np.exp(np.concatenate([[np.log(close[0])],
                                        np.cumsum(perm) + np.log(close[0])]))
    scale = new_close / close
    df2 = df.copy()
    df2["close"] = new_close
    df2["open"] = df["open"].to_numpy() * scale
    df2["high"] = df["high"].to_numpy() * scale
    df2["low"] = df["low"].to_numpy() * scale
    return df2

def build_sleeve_from_df(sleeve_label, df, variant):
    script, fn, _, _ = SLEEVE_SPECS[sleeve_label]
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

def build_combo_from_dfs(dfs_by_symbol):
    curves = {}
    for sleeve, variant in BEST_VARIANT_MAP.items():
        sym = SLEEVE_SPECS[sleeve][2]
        curves[sleeve] = build_sleeve_from_df(sleeve, dfs_by_symbol[sym], variant)

    p3_eq = invvol_blend({k: curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5_eq = eqw_blend({k: curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3_eq.index.intersection(p5_eq.index)
    r = (0.6 * p3_eq.reindex(idx).pct_change().fillna(0)
         + 0.4 * p5_eq.reindex(idx).pct_change().fillna(0))
    return (1 + r).cumprod() * 10_000.0

def sharpe(eq):
    r = eq.pct_change().dropna()
    sd = float(r.std())
    return (float(r.mean())/sd)*np.sqrt(BPY) if sd > 0 else 0

def main():
    t0 = time.time()
    # Real
    print("Loading real symbol data...")
    real_dfs = {s: load_data(s, "4h", start="2021-01-01", end="2026-03-31") for s in SYMBOLS}
    real_eq = build_combo_from_dfs(real_dfs)
    real_sh = sharpe(real_eq)
    print(f"Real Sharpe = {real_sh:.3f}")

    n_perm = 30
    rng = np.random.default_rng(42)
    null_shs = []
    for k in range(n_perm):
        shuffled = {s: shuffle_df_lr(real_dfs[s], rng) for s in SYMBOLS}
        try:
            eq_p = build_combo_from_dfs(shuffled)
            null_shs.append(sharpe(eq_p))
        except Exception as e:
            print(f"  perm {k}: {type(e).__name__}")
        if (k+1) % 5 == 0:
            print(f"  permutation {k+1}/{n_perm} done")

    arr = np.asarray(null_shs)
    p_val = float((arr >= real_sh).mean())
    print(f"\nReal Sharpe    = {real_sh:.3f}")
    print(f"Null mean      = {arr.mean():.3f}")
    print(f"Null 99th%ile  = {np.quantile(arr, 0.99):.3f}")
    print(f"p-value        = {p_val:.4f}")
    print(f"GATE 7 (p<0.01): {'PASS' if p_val < 0.01 else 'FAIL'}")

    result = {
        "real_sharpe": real_sh,
        "null_shs": null_shs,
        "null_mean": float(arr.mean()),
        "null_99th": float(np.quantile(arr, 0.99)),
        "p_value": p_val,
        "pass_p_lt_0_01": p_val < 0.01,
        "n_permutations": n_perm,
    }
    with open(OUT / "v41_champion_gate7_proper.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nTime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
