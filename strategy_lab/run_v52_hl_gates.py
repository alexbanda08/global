"""
Full 10-gate battery on V52 champion using Hyperliquid data + funding.

Reuses gate infrastructure from prior scripts but feeds HL OHLCV + funding
through the funding-aware simulator. Window: 2024-01-12 -> 2026-04-25.
"""
from __future__ import annotations
import importlib.util, json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator import simulate as sim_canonical
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit, REGIME_EXITS_4H
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend, verdict_8gate
from strategy_lab.run_leverage_gates910 import gate9_path_shuffle, gate10_forward_paths
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

START = "2024-01-12"
END = "2026-04-25"

# V41 BEST_VARIANT_MAP (champion sleeves)
V41_VARIANT_MAP = {
    "CCI_ETH_4h":    "V41",
    "STF_SOL_4h":    "baseline",
    "STF_AVAX_4h":   "V45",
    "LATBB_AVAX_4h": "baseline",
}

SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",  "sig_cci_extreme",     "ETH"),
    "STF_SOL_4h":    ("run_v30_creative.py",  "sig_supertrend_flip", "SOL"),
    "STF_AVAX_4h":   ("run_v30_creative.py",  "sig_supertrend_flip", "AVAX"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",    "sig_lateral_bb_fade", "AVAX"),
}

DIV_SPECS = [
    ("MFI_SOL",  "SOL",  sig_mfi_extreme,        dict(lower=25, upper=75), "V41"),
    ("VP_LINK",  "LINK", sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
    ("SVD_AVAX", "AVAX", sig_signed_vol_div,     dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
    ("MFI_ETH",  "ETH",  sig_mfi_extreme,        dict(lower=25, upper=75), "baseline"),
]

def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".","_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)

def build_v41_sleeve(sleeve, df_override=None):
    script, fn, sym = SLEEVE_SPECS[sleeve]
    sig = import_sig(script, fn)
    df = df_override if df_override is not None else load_hl(sym, "4h", start=START, end=END)
    out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    variant = V41_VARIANT_MAP[sleeve]

    if variant == "baseline":
        _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
    elif variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H)
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le2, se2, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H)
    return eq

def build_diversifier(name, df_override=None):
    spec = next(s for s in DIV_SPECS if s[0] == name)
    _, sym, sig_fn, kw, exit_style = spec
    df = df_override if df_override is not None else load_hl(sym, "4h", start=START, end=END)
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
                                       regime_labels=rdf["label"],
                                       regime_exits=REGIME_EXITS_4H)
    else:
        _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
    return eq

def build_v52_hl(dfs_override=None):
    """Build full V52 HL champion with funding accrual. dfs_override is a
    dict of symbol -> df (used for permutation testing)."""
    v41_curves = {}
    for s in V41_VARIANT_MAP:
        sym = SLEEVE_SPECS[s][2]
        df_o = dfs_override.get(sym) if dfs_override else None
        v41_curves[s] = build_v41_sleeve(s, df_override=df_o)

    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = 0.6 * p3.reindex(idx).pct_change().fillna(0) + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    div_curves = {}
    for spec in DIV_SPECS:
        sym = spec[1]
        df_o = dfs_override.get(sym) if dfs_override else None
        div_curves[spec[0]] = build_diversifier(spec[0], df_override=df_o)

    all_idx = v41_eq.index
    for eq in div_curves.values():
        all_idx = all_idx.intersection(eq.index)
    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_curves.items()}
    combined = (0.60 * cr + 0.10 * drs["MFI_SOL"] + 0.10 * drs["VP_LINK"]
                + 0.10 * drs["SVD_AVAX"] + 0.10 * drs["MFI_ETH"])
    v52_eq = (1 + combined).cumprod() * 10_000.0
    return v52_eq

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

def sharpe(eq):
    r = eq.pct_change().dropna()
    sd = float(r.std())
    return (float(r.mean())/sd)*np.sqrt(BPY) if sd > 0 else 0


def main():
    t0 = time.time()
    print("="*70)
    print("V52 Hyperliquid 10-gate battery (with funding accrual)")
    print(f"Window: {START} -> {END}")
    print("="*70)

    # Build the champion equity once
    print("\nBuilding HL V52 champion...")
    v52_eq = build_v52_hl()
    rets = v52_eq.pct_change().dropna()
    real_sh = sharpe(v52_eq)
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

    print(f"Headline: Sharpe={real_sh:.3f} CAGR={cagr*100:+.1f}% "
          f"MDD={mdd*100:+.1f}% Calmar={cal:.2f}")
    print(f"Yearly: {[(y, f'{r*100:+.1f}%') for y,r in yearly.items()]}")

    # Gates 1-6 via verdict_8gate (which actually returns 6 + 2 skipped)
    print("\n--- Gates 1-6 ---")
    g6 = verdict_8gate(v52_eq)
    print(f"  {g6['tests_passed']}")
    for gn, g in g6["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"    [{mark:4s}] {gn:38s} -> {g['value']}")

    # Gate 7: asset-level permutation
    print("\n--- Gate 7: asset-level permutation (n=30) ---")
    real_dfs = {sym: load_hl(sym, "4h", start=START, end=END)
                for sym in ["ETH","AVAX","SOL","LINK"]}
    rng = np.random.default_rng(42)
    null_shs = []
    for k in range(30):
        shuffled = {sym: shuffle_df_lr(df, rng) for sym, df in real_dfs.items()}
        try:
            eq_p = build_v52_hl(dfs_override=shuffled)
            null_shs.append(sharpe(eq_p))
        except Exception as e:
            print(f"  perm {k}: {type(e).__name__}")
        if (k+1) % 5 == 0:
            print(f"    perm {k+1}/30 done")
    arr = np.asarray(null_shs)
    p_val = float((arr >= real_sh).mean())
    print(f"  Real Sharpe={real_sh:.3f}  Null mean={arr.mean():.3f}  "
          f"99th%ile={np.quantile(arr, 0.99):.3f}  p={p_val:.4f}")
    print(f"  GATE 7: {'PASS' if p_val < 0.01 else 'FAIL'}")

    # Gate 9: path-shuffle MC
    print("\n--- Gate 9: path-shuffle MC (n=10000) ---")
    g9 = gate9_path_shuffle(v52_eq, n_iter=10_000)
    print(f"  MDD 5th={g9['mdd_p5']*100:.1f}%  median={g9['mdd_p50']*100:.1f}%  "
          f"GATE 9: {'PASS' if g9['gate9_pass'] else 'FAIL'}")

    # Gate 10: forward 1y MC
    print("\n--- Gate 10: forward 1y MC (n=1000) ---")
    g10 = gate10_forward_paths(v52_eq, n_paths=1000, year_bars=2190)
    print(f"  1y MDD: 5th={g10['mdd_p5']*100:.1f}% median={g10['mdd_p50']*100:.1f}%")
    print(f"  1y CAGR: 5th={g10['cagr_p5']*100:.1f}% median={g10['cagr_p50']*100:.1f}%")
    print(f"  P(neg yr)={g10['p_negative_year_pct']}%  P(DD>20%)={g10['p_dd_worse_than_20pct']}%  "
          f"P(DD>30%)={g10['p_dd_worse_than_30pct']}%")
    print(f"  GATE 10: {'PASS' if g10['gate10_pass'] else 'FAIL'}")

    # Save
    summary = {
        "candidate": "V52_CHAMPION_HL_WITH_FUNDING",
        "window_start": START, "window_end": END,
        "headline": {"sharpe": round(real_sh, 3), "cagr": round(cagr, 4),
                      "mdd": round(mdd, 4), "calmar": round(cal, 3),
                      "yearly": {y: round(r, 4) for y,r in yearly.items()}},
        "gates_1_6": g6,
        "gate7_permutation": {"p_value": p_val, "real_sharpe": real_sh,
                               "null_mean": float(arr.mean()),
                               "null_99th": float(np.quantile(arr, 0.99)),
                               "pass": p_val < 0.01,
                               "n_permutations": int(len(arr))},
        "gate9_path_shuffle": g9,
        "gate10_forward_paths": g10,
    }
    with open(OUT / "v52_hl_champion_audit.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSaved -> {OUT}/v52_hl_champion_audit.json")
    print(f"Total: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
