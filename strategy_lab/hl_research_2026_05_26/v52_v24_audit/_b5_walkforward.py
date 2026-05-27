"""B5 — Walk-forward verification of best gate variants per sleeve.
Best gates (from B2): FUND_Z<2 for CCI_ETH/STF_SOL/STF_AVAX/LATBB_AVAX,
                       ATR_NOTOPVOL for MFI_SOL/VP_LINK/MFI_ETH/SVD_AVAX
4-fold WF per sleeve.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0, "C:/Users/alexandre bandarra/Desktop/global")
import warnings; warnings.filterwarnings("ignore")

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model

import importlib.util
def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
v30 = load_mod("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/run_v30_creative.py", "v30c")
v29 = load_mod("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/run_v29_regime.py", "v29r")

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
BPY = 365.25 * 6
START = "2024-01-12"; END = "2026-04-25"

def sharpe(eq):
    r = eq.pct_change().dropna()
    if len(r) < 30: return 0.0
    sd = float(r.std())
    return (float(r.mean())/sd)*np.sqrt(BPY) if sd>0 else 0.0

def gate_atr_size(df, atr_n=14, low_q=0.20, high_q=0.80):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h-l), (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_n).mean()
    pct = atr.rolling(500, min_periods=100).rank(pct=True)
    smult = pd.Series(1.0, index=df.index)
    smult[pct <= low_q] = 1.5
    smult[pct >= high_q] = 0.5
    return smult.fillna(1.0)

def gate_funding_z(sym, df, z_thr=2.0):
    fund_4h = funding_per_4h_bar(sym, df.index)
    mu = fund_4h.rolling(500, min_periods=100).mean()
    sd = fund_4h.rolling(500, min_periods=100).std()
    z = (fund_4h - mu) / sd.replace(0, np.nan)
    return (z.abs() < z_thr).fillna(True)

def build_eq(sym, sig_fn, kw, variant, gate_label, df, fund):
    out = sig_fn(df, **kw)
    le, se = (out if isinstance(out, tuple) else (out, None))
    if gate_label == "FUND_Z<2":
        mask = gate_funding_z(sym, df, 2.0)
        le = le & mask
        if se is not None: se = se & mask
    elif gate_label == "ATR_NOTOPVOL":
        smult = gate_atr_size(df, low_q=0.20, high_q=0.80)
        mask = smult >= 1.0
        le = le & mask
        if se is not None: se = se & mask
    elif gate_label == "BASELINE":
        pass

    if variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund, regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le = le & active
        if se is not None: se = se & active
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund, regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
    else:
        _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
    return eq

# Sleeves with their best gate per B2 results
WINNERS = [
    ("CCI_ETH",    "ETH",  v30.sig_cci_extreme,      dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14), "V41",       "FUND_Z<2"),
    ("STF_SOL",    "SOL",  v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200), "baseline",                          "FUND_Z<2"),
    ("STF_AVAX",   "AVAX", v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200), "V45",                               "FUND_Z<2"),
    ("LATBB_AVAX", "AVAX", v29.sig_lateral_bb_fade,  dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14), "baseline",                    "FUND_Z<2"),
    ("MFI_SOL",    "SOL",  sig_mfi_extreme,          dict(lower=25, upper=75), "V41",                                              "ATR_NOTOPVOL"),
    ("VP_LINK",    "LINK", sig_volume_profile_rot,   dict(win=60, n_bins=15), "baseline",                                          "ATR_NOTOPVOL"),
    ("SVD_AVAX",   "AVAX", sig_signed_vol_div,       dict(lookback=20, cvd_win=50), "baseline",                                    "ATR_NOTOPVOL"),
    ("MFI_ETH",    "ETH",  sig_mfi_extreme,          dict(lower=25, upper=75), "baseline",                                         "ATR_NOTOPVOL"),
]

# 4-fold walk-forward
n_folds = 4
print("="*100)
print("B5 — 4-fold walk-forward on best-gate variants")
print("="*100)
print(f"{'sleeve':14} {'gate':14} | {'F1_oos':>8} {'F2_oos':>8} {'F3_oos':>8} {'F4_oos':>8} | {'mean_oos':>9} {'BASELINE':>9}")
wf_rows = []
for name, sym, sig_fn, kw, variant, gate_label in WINNERS:
    df = load_hl(sym, "4h", start=START, end=END)
    fund = funding_per_4h_bar(sym, df.index)
    # Build full equity once for both baseline & gated
    eq_base_full = build_eq(sym, sig_fn, kw, variant, "BASELINE", df, fund)
    eq_gate_full = build_eq(sym, sig_fn, kw, variant, gate_label, df, fund)

    # 4 folds: each fold is 1/4 of the data, contiguous, OOS portion
    n = len(eq_gate_full)
    fold_oos = []
    base_oos = []
    for k in range(n_folds):
        lo = int(n * k / n_folds)
        hi = int(n * (k+1) / n_folds)
        eq_fold = eq_gate_full.iloc[lo:hi]
        eq_fold_base = eq_base_full.iloc[lo:hi]
        fold_oos.append(sharpe(eq_fold))
        base_oos.append(sharpe(eq_fold_base))
    mean_g = float(np.mean(fold_oos))
    mean_b = float(np.mean(base_oos))
    print(f"{name:14} {gate_label:14} | {fold_oos[0]:>8.3f} {fold_oos[1]:>8.3f} {fold_oos[2]:>8.3f} {fold_oos[3]:>8.3f} | "
          f"{mean_g:>9.3f} {mean_b:>9.3f}")
    wf_rows.append(dict(sleeve=name, gate=gate_label,
        f1=round(fold_oos[0],3), f2=round(fold_oos[1],3),
        f3=round(fold_oos[2],3), f4=round(fold_oos[3],3),
        mean_gated=round(mean_g,3), mean_baseline=round(mean_b,3),
        lift=round(mean_g-mean_b,3)))
dfw = pd.DataFrame(wf_rows)
dfw.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/b5_walkforward_metrics.csv", index=False)

# === Permutation test on top variant ===
# Quick variant: STF_AVAX + FUND_Z<2 (was 2.30 Sh from 2.10)
print()
print("="*70)
print("Permutation test (n=100) on STF_AVAX_V45 + FUND_Z<2 gate")
print("="*70)
name, sym, sig_fn, kw, variant, gate_label = WINNERS[2]  # STF_AVAX
df = load_hl(sym, "4h", start=START, end=END)
fund = funding_per_4h_bar(sym, df.index)
real_eq = build_eq(sym, sig_fn, kw, variant, gate_label, df, fund)
real_sh = sharpe(real_eq)

rng = np.random.default_rng(42)
null = []
for k in range(100):
    # shuffle log returns to break causal structure
    close = df["close"].to_numpy()
    log_r = np.diff(np.log(close))
    perm = rng.permutation(log_r)
    new_close = np.exp(np.concatenate([[np.log(close[0])], np.cumsum(perm) + np.log(close[0])]))
    scale = new_close / close
    df2 = df.copy()
    df2["close"] = new_close
    df2["open"] = df["open"].to_numpy() * scale
    df2["high"] = df["high"].to_numpy() * scale
    df2["low"]  = df["low"].to_numpy() * scale
    try:
        eq_null = build_eq(sym, sig_fn, kw, variant, gate_label, df2, fund)
        null.append(sharpe(eq_null))
    except Exception as e:
        null.append(0.0)
arr = np.array(null)
p_val = float((arr >= real_sh).mean())
print(f"Real Sharpe: {real_sh:.3f}")
print(f"Null mean:   {arr.mean():.3f}")
print(f"Null 99th:   {np.quantile(arr, 0.99):.3f}")
print(f"p-value:     {p_val:.3f}")

import json
with open("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/b5_permutation_stf_avax_fundz.json", "w") as f:
    json.dump(dict(real_sh=real_sh, null_mean=float(arr.mean()), null_99th=float(np.quantile(arr,0.99)),
                   p_value=p_val, n=100), f, indent=2)
print("Saved -> b5_walkforward_metrics.csv + b5_permutation_stf_avax_fundz.json")
