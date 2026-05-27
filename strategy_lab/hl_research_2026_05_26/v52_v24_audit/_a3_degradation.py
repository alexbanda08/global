"""PHASE A3 — Why is 2026 degrading? Per-sleeve year-over-year Sharpe + funding cost.
Also V24 multi-filter pass-rate audit.
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

# (name, sym, sig, kwargs, variant): variant ∈ {baseline, V41, V45}
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
    df = load_hl(sym, "4h", start="2024-01-12", end="2026-04-25")
    out = sig_fn(df, **kw)
    if isinstance(out, tuple):
        le, se = out
    else:
        le, se = out, None
    fund = funding_per_4h_bar(sym, df.index)
    if variant == "baseline":
        _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
    elif variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le, se, fund,
            regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        _, eq = simulate_with_funding(df, le2, se2, fund,
            regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
    return eq, df, fund

def sharpe_per_year(eq):
    rets = eq.pct_change().dropna()
    out = {}
    for yr in [2024, 2025, 2026]:
        r = rets[rets.index.year == yr]
        if len(r) < 30: continue
        sd = float(r.std())
        sh = (float(r.mean())/sd)*np.sqrt(BPY) if sd>0 else 0.0
        tot = (1+r).prod() - 1
        mdd = float(((eq[eq.index.year==yr] / eq[eq.index.year==yr].cummax()) - 1).min())
        out[yr] = dict(sharpe=round(sh,3), return_=round(tot,4), mdd=round(mdd,4), n=len(r))
    return out

print("="*100)
print("PER-SLEEVE PER-YEAR SHARPE / RETURN / MDD")
print("="*100)
print(f"{'sleeve':12} {'sym':5} | {'2024 Sh':9} {'2024 Ret':10} {'2025 Sh':9} {'2025 Ret':10} {'2026 Sh':9} {'2026 Ret':10}")
rows = []
for name, sym, sig_fn, kw, variant in SLEEVES:
    try:
        eq, df, fund = build_sleeve_eq(name, sym, sig_fn, kw, variant)
        per_yr = sharpe_per_year(eq)
        r24 = per_yr.get(2024, {})
        r25 = per_yr.get(2025, {})
        r26 = per_yr.get(2026, {})
        print(f"{name:12} {sym:5} | "
              f"{r24.get('sharpe',0):9.3f} {r24.get('return_',0)*100:+9.1f}% "
              f"{r25.get('sharpe',0):9.3f} {r25.get('return_',0)*100:+9.1f}% "
              f"{r26.get('sharpe',0):9.3f} {r26.get('return_',0)*100:+9.1f}%")
        rows.append(dict(sleeve=name, sym=sym, variant=variant,
            sh_2024=r24.get("sharpe",0), ret_2024=r24.get("return_",0),
            sh_2025=r25.get("sharpe",0), ret_2025=r25.get("return_",0),
            sh_2026=r26.get("sharpe",0), ret_2026=r26.get("return_",0),
        ))
    except Exception as e:
        print(f"{name}: FAIL {e}")
        rows.append(dict(sleeve=name, sym=sym, variant=variant, error=str(e)))

dfo = pd.DataFrame(rows)
dfo.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/a3_per_yr_sleeve.csv", index=False)

# === Funding cost regime check 2024 vs 2025 vs 2026 ===
print()
print("="*70)
print("FUNDING RATE REGIME PER YEAR (mean 4h-aggregated abs rate)")
print("="*70)
fund_rows = []
for sym in ["BTC","ETH","SOL","AVAX","LINK"]:
    df = load_hl(sym, "4h", start="2024-01-12", end="2026-04-25")
    fund = funding_per_4h_bar(sym, df.index)
    for yr in [2024, 2025, 2026]:
        m = fund[fund.index.year == yr]
        if len(m) < 30: continue
        # absolute funding rate (proxy for cost magnitude)
        mean_abs = float(m.abs().mean())*100  # in pct
        std_abs = float(m.abs().std())*100
        mean_signed = float(m.mean())*100  # if positive => longs paying
        print(f"{sym} {yr}: 4h_abs_mean={mean_abs*100:.4f}bps  4h_signed_mean={mean_signed*100:+.4f}bps  std={std_abs*100:.4f}bps  n_bars={len(m)}")
        fund_rows.append(dict(sym=sym, yr=yr, abs_mean_pct=round(mean_abs,5),
            signed_mean_pct=round(mean_signed,5), std_pct=round(std_abs,5), n=len(m)))
dff = pd.DataFrame(fund_rows)
dff.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/a3_funding_regimes.csv", index=False)

# === Volatility regime check 2024 vs 2025 vs 2026 ===
print()
print("="*70)
print("REALIZED VOL REGIME PER YEAR (4h log-ret stdev annualized)")
print("="*70)
vol_rows = []
for sym in ["BTC","ETH","SOL","AVAX","LINK"]:
    df = load_hl(sym, "4h", start="2024-01-12", end="2026-04-25")
    lr = np.log(df["close"]/df["close"].shift(1))
    for yr in [2024, 2025, 2026]:
        m = lr[lr.index.year == yr]
        if len(m) < 30: continue
        ann_vol = float(m.std()) * np.sqrt(365.25*6)
        ret = float((1+m).prod()-1)  # log compounded
        print(f"{sym} {yr}: ann_vol={ann_vol*100:.1f}%  spot_ret={ret*100:+.1f}%  n_bars={len(m)}")
        vol_rows.append(dict(sym=sym, yr=yr, ann_vol=round(ann_vol,4), spot_ret=round(ret,4)))
dfv = pd.DataFrame(vol_rows)
dfv.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/a3_vol_regimes.csv", index=False)
print("\nFiles saved to: hl_research_2026_05_26/v52_v24_audit/a3_*.csv")
