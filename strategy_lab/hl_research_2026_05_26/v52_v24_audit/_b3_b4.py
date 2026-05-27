"""B3 — V24-XSM relaxation simulator. B4 — V52/V24 portfolio blend."""
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
    return dict(sharpe=round(sh,3), cagr=round(cagr,4), mdd=round(mdd,4), calmar=round(cal,3))

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

# ============================================================
# B3 — V24 cross-sectional momentum, simplified inline sim
# Each rebalance, pick top-K coins by lookback return, equal-weight long.
# Apply gate filter on each rebal bar.
# ============================================================
COINS = ["BTC","ETH","SOL","AVAX","LINK"]
BARS_PER_DAY = 6
INIT = 10_000.0
FEE = 0.00045
SLIP = 0.0003

def run_xsm(close, open_, top_k=2, lookback_days=14, rebal_days=7,
            gate_fn=None, label="?", leverage=1.0):
    """Equal-weight long-only top-K momentum on HL 4h."""
    idx = close.index
    n = len(idx)
    eq = np.empty(n); eq[0] = INIT
    cash = INIT
    positions = {s: 0.0 for s in COINS}
    step = rebal_days * BARS_PER_DAY
    lookback_bars = lookback_days * BARS_PER_DAY
    init_bars = max(lookback_bars, 100 * BARS_PER_DAY)
    for i in range(1, n):
        # current MTM
        mtm = cash + sum(positions[s] * close.iloc[i][s] for s in COINS if not np.isnan(close.iloc[i][s]))
        eq[i] = mtm
        if i < init_bars or (i - init_bars) % step != 0: continue
        # Gate active?
        if gate_fn is not None and not gate_fn(i):
            # close all
            for s in COINS:
                if positions[s] != 0:
                    px = open_.iloc[min(i+1, n-1)][s]
                    if np.isnan(px): continue
                    gross = positions[s] * px
                    fee = abs(gross) * FEE
                    cash += gross - fee
                    positions[s] = 0
            continue
        # Compute lookback returns
        rets = {}
        for s in COINS:
            p_now = close.iloc[i][s]; p_lb = close.iloc[i-lookback_bars][s]
            if np.isnan(p_now) or np.isnan(p_lb): continue
            rets[s] = float(p_now/p_lb - 1)
        if len(rets) < top_k: continue
        ranked = sorted(rets, key=lambda s: rets[s], reverse=True)
        winners = set(ranked[:top_k])
        # Rebalance: close losers, set winners equal-weight
        target_per_pos = (cash + sum(positions[s] * close.iloc[i][s] for s in COINS if not np.isnan(close.iloc[i][s]))) * leverage / top_k
        for s in COINS:
            if s not in winners:
                if positions[s] != 0:
                    px = open_.iloc[min(i+1, n-1)][s]
                    if np.isnan(px): continue
                    gross = positions[s] * px
                    fee = abs(gross) * FEE
                    cash += gross - fee
                    positions[s] = 0
        for s in winners:
            px = open_.iloc[min(i+1, n-1)][s]
            if np.isnan(px): continue
            tgt_units = target_per_pos / px
            delta = tgt_units - positions[s]
            cost = delta * px
            fee = abs(cost) * FEE
            cash -= (cost + fee)
            positions[s] = tgt_units
    eq_s = pd.Series(eq, index=idx)
    return eq_s

# Build close/open frames
dfs = {sym: load_hl(sym, "4h", start=START, end=END) for sym in COINS}
idx = None
for sym in COINS:
    idx = dfs[sym].index if idx is None else idx.intersection(dfs[sym].index)
close = pd.DataFrame({sym: dfs[sym]["close"].reindex(idx) for sym in COINS})
open_ = pd.DataFrame({sym: dfs[sym]["open"].reindex(idx) for sym in COINS})

# Gate builders
btc_ma100 = close["BTC"].rolling(100*BARS_PER_DAY).mean()
btc_ma50 = close["BTC"].rolling(50*BARS_PER_DAY).mean()
btc_above_100 = close["BTC"] > btc_ma100
btc_50_rising = btc_ma50 > btc_ma50.shift(BARS_PER_DAY)
per_coin_ma50 = {s: close[s].rolling(50*BARS_PER_DAY).mean() for s in COINS}
breadth = sum((close[s] > per_coin_ma50[s]).astype(int) for s in COINS)

def make_gate(filt):
    """Convert series → integer-index lookup fn."""
    arr = filt.fillna(False).to_numpy()
    return lambda i: bool(arr[i]) if i < len(arr) else False

configs = [
    ("ALWAYS_ON",                lambda i: True),
    ("V24_original_b5/5",        make_gate(btc_above_100 & btc_50_rising & (breadth>=5))),
    ("relaxed_b4/5",             make_gate(btc_above_100 & btc_50_rising & (breadth>=4))),
    ("relaxed_b3/5",             make_gate(btc_above_100 & btc_50_rising & (breadth>=3))),
    ("relaxed_drop_rising_b3/5", make_gate(btc_above_100 & (breadth>=3))),
    ("relaxed_BTC50_only",       make_gate(close["BTC"] > btc_ma50)),
    ("relaxed_BTC100_only",      make_gate(btc_above_100)),
]

print("="*120)
print("B3 — V24-XSM relaxation tests (top-2, 14d lookback, 7d rebal, leverage=1.0)")
print("="*120)
print(f"{'config':32} | {'Sh':>7} {'CAGR':>9} {'MDD':>8} {'Calmar':>7} | {'24':>7} {'25':>7} {'26':>7}")
rows = []
v24_curves = {}
for name, gate in configs:
    eq = run_xsm(close, open_, top_k=2, lookback_days=14, rebal_days=7, gate_fn=gate, label=name)
    v24_curves[name] = eq
    m = metrics(eq); yr = per_year_sh(eq)
    print(f"{name:32} | {m['sharpe']:7.3f} {m['cagr']*100:+8.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
          f"{yr.get(2024,0):7.3f} {yr.get(2025,0):7.3f} {yr.get(2026,0):7.3f}")
    rows.append(dict(config=name, **m, sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))

# Vol-target relaxation: ALWAYS_ON but scale by inverse rolling vol
# (simulate by reducing leverage to 0.5 with no gate)
eq_vt = run_xsm(close, open_, top_k=2, lookback_days=14, rebal_days=7, gate_fn=None, leverage=0.5)
m = metrics(eq_vt); yr = per_year_sh(eq_vt)
print(f"{'VOL_TARGET_lev0.5':32} | {m['sharpe']:7.3f} {m['cagr']*100:+8.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
      f"{yr.get(2024,0):7.3f} {yr.get(2025,0):7.3f} {yr.get(2026,0):7.3f}")
rows.append(dict(config="VOL_TARGET_lev0.5", **m, sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))
v24_curves["VOL_TARGET_lev0.5"] = eq_vt

dfo = pd.DataFrame(rows)
dfo.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/v24_relaxed_metrics.csv", index=False)
print("\nSaved -> v24_relaxed_metrics.csv")

# ============================================================
# B4 — V52 / V24 blend
# Recreate V52 champion equity from per-sleeve baselines (with weights 0.60 V41-core + 0.10×4 diversifiers)
# ============================================================
print()
print("="*100)
print("B4 — V52 + V24-XSM blend (V52 baseline = original spec)")
print("="*100)
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

def build_sleeve_eq(name, sym, sig_fn, kw, variant):
    df = load_hl(sym, "4h", start=START, end=END)
    fund = funding_per_4h_bar(sym, df.index)
    out = sig_fn(df, **kw)
    le, se = (out if isinstance(out, tuple) else (out, None))
    if variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
            regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le = le & active
        if se is not None: se = se & active
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
            regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
    else:
        _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
    return eq

# V52 = 0.25*0.60 per V41 sleeve + 0.10*4 diversifier (per spec line 60% V41 + 4×10% diversifiers)
# We have 4 V41 sleeves (CCI/STF_SOL/STF_AVAX/LATBB) → V41-block = mean of 4 → weight 0.60
# Then 4 diversifiers (MFI_SOL/VP_LINK/SVD_AVAX/MFI_ETH) @ 10% each = 0.40 total
all_eq = {}
for n, sym, sf, kw, var in SLEEVES:
    print(f"  Building {n}...")
    all_eq[n] = build_sleeve_eq(n, sym, sf, kw, var)

# Align all
idx_v52 = None
for eq in all_eq.values():
    idx_v52 = eq.index if idx_v52 is None else idx_v52.intersection(eq.index)

ret_df = pd.DataFrame({n: all_eq[n].reindex(idx_v52).pct_change().fillna(0) for n in all_eq})
v41_block_ret = ret_df[["CCI_ETH","STF_SOL","STF_AVAX","LATBB_AVAX"]].mean(axis=1)
combined_v52 = 0.60*v41_block_ret + 0.10*ret_df["MFI_SOL"] + 0.10*ret_df["VP_LINK"] + 0.10*ret_df["SVD_AVAX"] + 0.10*ret_df["MFI_ETH"]
eq_v52 = (1+combined_v52).cumprod() * 10_000.0
m = metrics(eq_v52); yr = per_year_sh(eq_v52)
print(f"\nV52_REBUILT     : Sharpe={m['sharpe']} CAGR={m['cagr']*100:+.1f}% MDD={m['mdd']*100:+.1f}% Calmar={m['calmar']} | 24={yr.get(2024,0)} 25={yr.get(2025,0)} 26={yr.get(2026,0)}")

# Pick best V24 — say relaxed_b3/5 (best validated relaxation)
# Pick from B3 results dataframe
best_v24_label = max(rows, key=lambda r: r["sharpe"] if r["mdd"] > -0.4 else -99)["config"]
eq_v24_best = v24_curves[best_v24_label]
m_v24 = metrics(eq_v24_best); yr_v24 = per_year_sh(eq_v24_best)
print(f"V24_BEST({best_v24_label}): Sharpe={m_v24['sharpe']} CAGR={m_v24['cagr']*100:+.1f}% MDD={m_v24['mdd']*100:+.1f}% Calmar={m_v24['calmar']} | 24={yr_v24.get(2024,0)} 25={yr_v24.get(2025,0)} 26={yr_v24.get(2026,0)}")

# Blends V52 + V24
print()
print(f"{'blend':32} | {'Sh':>7} {'CAGR':>9} {'MDD':>8} {'Calmar':>7} | {'24':>7} {'25':>7} {'26':>7}")
blend_rows = []
v24_ret = eq_v24_best.reindex(idx_v52).pct_change().fillna(0)
v52_ret_full = combined_v52
for w52 in [1.0, 0.70, 0.50, 0.30, 0.0]:
    w24 = 1 - w52
    blend_ret = w52*v52_ret_full + w24*v24_ret
    blend_eq = (1+blend_ret).cumprod() * 10_000.0
    m = metrics(blend_eq); yr = per_year_sh(blend_eq)
    print(f"V52={w52:.0%} V24={w24:.0%}           | {m['sharpe']:7.3f} {m['cagr']*100:+8.1f}% {m['mdd']*100:+7.1f}% {m['calmar']:7.3f} | "
          f"{yr.get(2024,0):7.3f} {yr.get(2025,0):7.3f} {yr.get(2026,0):7.3f}")
    corr = v52_ret_full.corr(v24_ret)
    blend_rows.append(dict(blend=f"V52={w52:.0%}_V24={w24:.0%}", w52=w52, w24=w24, **m,
        sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0),
        corr_v52_v24=round(corr,3)))

print(f"\nCorrelation V52 vs V24-best returns: {v52_ret_full.corr(v24_ret):.3f}")

dfb = pd.DataFrame(blend_rows)
dfb.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/portfolio_blend_metrics.csv", index=False)
print("\nSaved -> portfolio_blend_metrics.csv")
