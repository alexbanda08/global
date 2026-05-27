"""PHASE B1 — V52-BTC sleeve candidate testing.
Test on HL BTC 4h 2024-01-12 to 2026-04-25, with funding.
Candidates: CCI extreme, SuperTrend flip, Donchian breakout.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0, "C:/Users/alexandre bandarra/Desktop/global")
import warnings; warnings.filterwarnings("ignore")

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
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

import talib

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
BPY = 365.25 * 6

def sig_donchian_break(df, n=20, n_exit=10):
    """Long when close >= prior N-bar high; short when close <= prior N-bar low.
    Standard Donchian (turtle) entry."""
    hi_n = df["high"].rolling(n).max().shift(1)
    lo_n = df["low"].rolling(n).min().shift(1)
    long_e = df["close"] > hi_n
    short_e = df["close"] < lo_n
    return long_e.fillna(False), short_e.fillna(False)

def sig_donch_pullback(df, n=20, ema_n=200):
    """Donchian breakout filtered by EMA-200 regime."""
    le, se = sig_donchian_break(df, n)
    ema_r = df["close"].ewm(span=ema_n, adjust=False).mean()
    le = le & (df["close"] > ema_r)
    se = se & (df["close"] < ema_r)
    return le, se

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
        calmar=round(cal,3), end_eq=round(float(eq.iloc[-1]),2))

def per_year(eq):
    out = {}
    rets = eq.pct_change().dropna()
    for yr in [2024, 2025, 2026]:
        r = rets[rets.index.year == yr]
        if len(r) < 30: continue
        sd = float(r.std())
        sh = (float(r.mean())/sd)*np.sqrt(BPY) if sd>0 else 0.0
        out[yr] = round(sh, 3)
    return out

df = load_hl("BTC", "4h", start="2024-01-12", end="2026-04-25")
fund = funding_per_4h_bar("BTC", df.index)
print(f"BTC data: {df.index[0]} -> {df.index[-1]}  n={len(df)}")
print()

candidates = []

# 1. CCI extreme
le, se = v30.sig_cci_extreme(df, cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22)
_, eq_baseline = simulate_with_funding(df, le, se, fund, **EXIT_4H)
candidates.append(("CCI_BTC_baseline", eq_baseline, int(le.sum()+se.sum())))

_, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
_, eq_v41 = simulate_with_funding(df, le, se, fund,
    regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
candidates.append(("CCI_BTC_V41", eq_v41, int(le.sum()+se.sum())))

# 2. SuperTrend
le, se = v30.sig_supertrend_flip(df, st_n=10, st_mult=3.0, ema_reg=200)
_, eq_stf = simulate_with_funding(df, le, se, fund, **EXIT_4H)
candidates.append(("STF_BTC_baseline", eq_stf, int(le.sum()+se.sum())))

# V45-style volume gate
vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
active = vol > 1.1 * vmean
_, eq_stf_v45 = simulate_with_funding(df, le & active, se & active, fund,
    regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
candidates.append(("STF_BTC_V45", eq_stf_v45, int((le & active).sum()+(se & active).sum())))

# 3. Donchian
le, se = sig_donchian_break(df, n=20)
_, eq_d20 = simulate_with_funding(df, le, se, fund, **EXIT_4H)
candidates.append(("DONCH_BTC_20", eq_d20, int(le.sum()+se.sum())))

le, se = sig_donchian_break(df, n=55)
_, eq_d55 = simulate_with_funding(df, le, se, fund, **EXIT_4H)
candidates.append(("DONCH_BTC_55", eq_d55, int(le.sum()+se.sum())))

le, se = sig_donch_pullback(df, n=20, ema_n=200)
_, eq_dp = simulate_with_funding(df, le, se, fund, **EXIT_4H)
candidates.append(("DONCH_BTC_20_EMA200", eq_dp, int(le.sum()+se.sum())))

le, se = sig_donch_pullback(df, n=55, ema_n=200)
_, eq_dp55 = simulate_with_funding(df, le, se, fund, **EXIT_4H)
candidates.append(("DONCH_BTC_55_EMA200", eq_dp55, int(le.sum()+se.sum())))

# Donchian + V41 regime
le, se = sig_donch_pullback(df, n=20, ema_n=200)
_, eq_dp_v41 = simulate_with_funding(df, le, se, fund,
    regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
candidates.append(("DONCH_BTC_20_EMA200_V41", eq_dp_v41, int(le.sum()+se.sum())))

# Long-only Donchian (avoid shorts on BTC where bias is up)
le, se = sig_donch_pullback(df, n=20, ema_n=200)
se_zero = pd.Series(False, index=df.index)
_, eq_dp_long = simulate_with_funding(df, le, se_zero, fund, **EXIT_4H)
candidates.append(("DONCH_BTC_20_LONGONLY", eq_dp_long, int(le.sum())))

print(f"{'Sleeve':30} {'Sh':>7} {'CAGR':>8} {'MDD':>8} {'Calmar':>8} {'fires':>7} | "
      f"{'24':>7} {'25':>7} {'26':>7}")
rows = []
for name, eq, n_fires in candidates:
    m = metrics(eq)
    yr = per_year(eq)
    print(f"{name:30} {m['sharpe']:7.3f} {m['cagr']*100:+7.1f}% {m['mdd']*100:+7.1f}% "
          f"{m['calmar']:7.3f} {n_fires:>7} | "
          f"{yr.get(2024,0):7.3f} {yr.get(2025,0):7.3f} {yr.get(2026,0):7.3f}")
    rows.append(dict(sleeve=name, **m, fires=n_fires,
        sh_2024=yr.get(2024,0), sh_2025=yr.get(2025,0), sh_2026=yr.get(2026,0)))
df_out = pd.DataFrame(rows)
df_out.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/b1_v52_btc_candidates.csv", index=False)
print()
print("Saved -> b1_v52_btc_candidates.csv")
