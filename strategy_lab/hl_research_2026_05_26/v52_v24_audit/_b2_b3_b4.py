"""PHASE B2 / B3 / B4 — Gate overlays on existing V52 sleeves + V24 relaxations + portfolio blend.

B2 — apply new gates to each V52 sleeve, measure Sharpe lift:
   - markov regime sizing (3-state vol regimes)
   - vol-regime sizing (ATR percentile)
   - funding extreme filter
B3 — V24-XSM filter relaxation
B4 — V52+V24 portfolio blend
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
# inline blend funcs (avoid broken import chain)
def eqw_blend(curves):
    idx = None
    for eq in curves.values():
        idx = eq.index if idx is None else idx.intersection(eq.index)
    rets = pd.DataFrame({k: curves[k].reindex(idx).pct_change().fillna(0) for k in curves})
    return (1 + rets.mean(axis=1)).cumprod() * 10_000.0

def invvol_blend(curves, window=500):
    idx = None
    for eq in curves.values():
        idx = eq.index if idx is None else idx.intersection(eq.index)
    rets = pd.DataFrame({k: curves[k].reindex(idx).pct_change().fillna(0) for k in curves})
    vol = rets.rolling(window, min_periods=max(20, window//4)).std()
    inv_vol = 1.0 / vol.replace(0, np.nan)
    weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(1.0/len(curves))
    return (1 + (rets*weights).sum(axis=1)).cumprod() * 10_000.0

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

# =============================================================
# B2: Gates
# =============================================================
def gate_markov_size(df, window=20, q_low=0.30, q_high=0.70):
    """3-state vol regime from rolling 20-bar log-ret quantile.
    Returns size_mult: 1.5× low-vol, 1× mid, 0.5× high-vol."""
    lr = np.log(df["close"]/df["close"].shift(1))
    sigma = lr.rolling(window).std()
    # Percentile-rank of current sigma vs prior 500 bars
    rolling_q = sigma.rolling(500, min_periods=100).rank(pct=True)
    smult = pd.Series(1.0, index=df.index)
    smult[rolling_q <= q_low] = 1.5
    smult[rolling_q >= q_high] = 0.5
    return smult.fillna(1.0)

def gate_atr_size(df, atr_n=14, low_q=0.30, high_q=0.70):
    """ATR-percentile sizing: low vol → 1.5×, high vol → 0.5×."""
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h-l), (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_n).mean()
    pct = atr.rolling(500, min_periods=100).rank(pct=True)
    smult = pd.Series(1.0, index=df.index)
    smult[pct <= low_q] = 1.5
    smult[pct >= high_q] = 0.5
    return smult.fillna(1.0)

def gate_funding_extreme_filter(sym, df, z_thr=2.0):
    """Returns a bool mask: True where |funding_z| < z_thr (i.e., NOT extreme)."""
    fund_4h = funding_per_4h_bar(sym, df.index)
    # rolling z-score of 4h funding rate over 500 bars
    mu = fund_4h.rolling(500, min_periods=100).mean()
    sd = fund_4h.rolling(500, min_periods=100).std()
    z = (fund_4h - mu) / sd.replace(0, np.nan)
    ok_mask = z.abs() < z_thr
    return ok_mask.fillna(True)

def gate_taker_balance(df, lookback=20):
    """If taker_buy_base / taker_buy_quote present, build a balance mask.
    Long signals pass when buyer-side is dominant (taker_buy_base/volume > 0.5).
    Most HL parquets don't have taker columns; fall back to True."""
    if "taker_buy_base" in df.columns and "volume" in df.columns:
        ratio = (df["taker_buy_base"] / df["volume"]).rolling(lookback).mean()
        long_ok = ratio > 0.5
        short_ok = ratio < 0.5
        return long_ok.fillna(True), short_ok.fillna(True)
    return pd.Series(True, index=df.index), pd.Series(True, index=df.index)

def metrics(eq):
    rets = eq.pct_change().dropna()
    if len(rets) < 30: return dict(sharpe=0,cagr=0,mdd=0,calmar=0)
    sd = float(rets.std())
    sh = (float(rets.mean())/sd)*np.sqrt(BPY) if sd>0 else 0.0
    yrs = (eq.index[-1] - eq.index[0]).total_seconds()/(365.25*86400)
    tot = float(eq.iloc[-1]/eq.iloc[0]-1)
    cagr = (1+tot)**(1/max(yrs,1e-6))-1
    mdd = float(((eq/eq.cummax())-1).min())
    cal = cagr/abs(mdd) if mdd != 0 else 0
    return dict(sharpe=round(sh,3), cagr=round(cagr,4), mdd=round(mdd,4),
        calmar=round(cal,3))

def per_year_sh(eq):
    out = {}
    rets = eq.pct_change().dropna()
    for yr in [2024, 2025, 2026]:
        r = rets[rets.index.year == yr]
        if len(r) < 30: continue
        sd = float(r.std())
        sh = (float(r.mean())/sd)*np.sqrt(BPY) if sd>0 else 0.0
        out[yr] = round(sh, 3)
    return out

SLEEVES = [
    ("CCI_ETH",   "ETH",  v30.sig_cci_extreme,         dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14), "V41"),
    ("STF_SOL",   "SOL",  v30.sig_supertrend_flip,     dict(st_n=10, st_mult=3.0, ema_reg=200), "baseline"),
    ("STF_AVAX",  "AVAX", v30.sig_supertrend_flip,     dict(st_n=10, st_mult=3.0, ema_reg=200), "V45"),
    ("LATBB_AVAX","AVAX", v29.sig_lateral_bb_fade,     dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14), "baseline"),
    ("MFI_SOL",   "SOL",  sig_mfi_extreme,             dict(lower=25, upper=75), "V41"),
    ("VP_LINK",   "LINK", sig_volume_profile_rot,      dict(win=60, n_bins=15), "baseline"),
    ("SVD_AVAX",  "AVAX", sig_signed_vol_div,          dict(lookback=20, cvd_win=50), "baseline"),
    ("MFI_ETH",   "ETH",  sig_mfi_extreme,             dict(lower=25, upper=75), "baseline"),
]

def build_eq_with_overrides(sym, sig_fn, kw, variant, df, fund, le_mask=None, se_mask=None, size_mult=None):
    """Apply optional masks + size multiplier on top of base sleeve config."""
    out = sig_fn(df, **kw)
    if isinstance(out, tuple):
        le, se = out
    else:
        le, se = out, None
    if le_mask is not None: le = le & le_mask
    if se_mask is not None and se is not None: se = se & se_mask
    kwargs = dict(EXIT_4H)
    if size_mult is not None: kwargs["size_mult"] = size_mult
    if variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
            regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H, **{k:v for k,v in kwargs.items() if k != "size_mult"})
        # size_mult only used if param supported; check signature
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le = le & active
        if se is not None: se = se & active
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
            regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H, **{k:v for k,v in kwargs.items() if k != "size_mult"})
    else:
        _, eq = simulate_with_funding(df, le, se, fund, **kwargs)
    return eq

import inspect
sig_params = list(inspect.signature(simulate_with_funding).parameters.keys())
print(f"simulate_with_funding params: {sig_params}")

print()
print("="*120)
print("B2 — Gate overlays per sleeve (vs baseline)")
print("="*120)
print(f"{'sleeve':14} {'gate':18} | {'Sh':>7} {'CAGR':>8} {'MDD':>8} {'Calmar':>7} | "
      f"{'24':>6} {'25':>6} {'26':>6}")

all_curves_baseline = {}
all_curves_best_gate = {}
all_rows = []
for name, sym, sig_fn, kw, variant in SLEEVES:
    df = load_hl(sym, "4h", start=START, end=END)
    fund = funding_per_4h_bar(sym, df.index)

    # Baseline
    eq_base = build_eq_with_overrides(sym, sig_fn, kw, variant, df, fund)
    all_curves_baseline[name] = eq_base
    m = metrics(eq_base); yr = per_year_sh(eq_base)
    print(f"{name:14} {'BASELINE':18} | {m['sharpe']:7.3f} {m['cagr']*100:+7.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
          f"{yr.get(2024,0):6.3f} {yr.get(2025,0):6.3f} {yr.get(2026,0):6.3f}")
    all_rows.append(dict(sleeve=name, gate="BASELINE", **m, sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))

    # Gate: ATR-vol-regime sizing — apply as entry filter (only enter when low-mid vol)
    atr_smult = gate_atr_size(df)
    # Implement as: only allow entries where smult>0 (skip when smult==0.5 we still enter, just downsize -- but sim has no size_mult)
    # Convert to filter: skip when high-vol (smult==0.5)
    atr_lowmid_mask = atr_smult >= 1.0
    eq_atr = build_eq_with_overrides(sym, sig_fn, kw, variant, df, fund,
        le_mask=atr_lowmid_mask, se_mask=atr_lowmid_mask)
    m = metrics(eq_atr); yr = per_year_sh(eq_atr)
    print(f"{name:14} {'ATR_LOWMID':18} | {m['sharpe']:7.3f} {m['cagr']*100:+7.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
          f"{yr.get(2024,0):6.3f} {yr.get(2025,0):6.3f} {yr.get(2026,0):6.3f}")
    all_rows.append(dict(sleeve=name, gate="ATR_LOWMID", **m, sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))

    # Gate: skip high-vol-extreme entries (top 20% only)
    atr_smult2 = gate_atr_size(df, low_q=0.20, high_q=0.80)
    not_extreme_high = atr_smult2 >= 1.0
    eq_no_high = build_eq_with_overrides(sym, sig_fn, kw, variant, df, fund,
        le_mask=not_extreme_high, se_mask=not_extreme_high)
    m = metrics(eq_no_high); yr = per_year_sh(eq_no_high)
    print(f"{name:14} {'ATR_NOTOPVOL':18} | {m['sharpe']:7.3f} {m['cagr']*100:+7.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
          f"{yr.get(2024,0):6.3f} {yr.get(2025,0):6.3f} {yr.get(2026,0):6.3f}")
    all_rows.append(dict(sleeve=name, gate="ATR_NOTOPVOL", **m, sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))

    # Gate: funding-z filter
    fund_ok = gate_funding_extreme_filter(sym, df, z_thr=2.0)
    eq_fund = build_eq_with_overrides(sym, sig_fn, kw, variant, df, fund,
        le_mask=fund_ok, se_mask=fund_ok)
    m = metrics(eq_fund); yr = per_year_sh(eq_fund)
    print(f"{name:14} {'FUND_Z<2':18} | {m['sharpe']:7.3f} {m['cagr']*100:+7.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
          f"{yr.get(2024,0):6.3f} {yr.get(2025,0):6.3f} {yr.get(2026,0):6.3f}")
    all_rows.append(dict(sleeve=name, gate="FUND_Z<2", **m, sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))

    # Gate: BTC trend gate — long only when BTC > BTC_EMA(200); short when BTC < EMA(200)
    df_btc = load_hl("BTC", "4h", start=START, end=END)
    btc_ema200 = df_btc["close"].ewm(span=200, adjust=False).mean()
    bull_btc = (df_btc["close"] > btc_ema200).reindex(df.index).ffill()
    bear_btc = ~bull_btc
    eq_btc = build_eq_with_overrides(sym, sig_fn, kw, variant, df, fund,
        le_mask=bull_btc, se_mask=bear_btc)
    m = metrics(eq_btc); yr = per_year_sh(eq_btc)
    print(f"{name:14} {'BTC_EMA200_GATE':18} | {m['sharpe']:7.3f} {m['cagr']*100:+7.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
          f"{yr.get(2024,0):6.3f} {yr.get(2025,0):6.3f} {yr.get(2026,0):6.3f}")
    all_rows.append(dict(sleeve=name, gate="BTC_EMA200_GATE", **m, sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))

# Save B2
df_b2 = pd.DataFrame(all_rows)
df_b2.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/optimized_v52_metrics.csv", index=False)
print("\nSaved -> optimized_v52_metrics.csv")
