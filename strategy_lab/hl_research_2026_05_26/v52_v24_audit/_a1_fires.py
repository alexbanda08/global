"""PHASE A1 — Verify V52 sleeve fire counts on latest 30/90/180d window."""
import sys, os
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0, "C:/Users/alexandre bandarra/Desktop/global")
import warnings; warnings.filterwarnings("ignore")

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

import importlib.util
def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

v30 = load_mod("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/run_v30_creative.py", "v30c")
v29 = load_mod("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/run_v29_regime.py", "v29r")

SLEEVES = [
    ("CCI_ETH",   "ETH",  v30.sig_cci_extreme,         dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14)),
    ("STF_SOL",   "SOL",  v30.sig_supertrend_flip,     dict(st_n=10, st_mult=3.0, ema_reg=200)),
    ("STF_AVAX",  "AVAX", v30.sig_supertrend_flip,     dict(st_n=10, st_mult=3.0, ema_reg=200)),
    ("LATBB_AVAX","AVAX", v29.sig_lateral_bb_fade,     dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14)),
    ("MFI_SOL",   "SOL",  sig_mfi_extreme,             dict(lower=25, upper=75)),
    ("VP_LINK",   "LINK", sig_volume_profile_rot,      dict(win=60, n_bins=15)),
    ("SVD_AVAX",  "AVAX", sig_signed_vol_div,          dict(lookback=20, cvd_win=50)),
    ("MFI_ETH",   "ETH",  sig_mfi_extreme,             dict(lower=25, upper=75)),
]

rows = []
for name, sym, sig_fn, kw in SLEEVES:
    df = load_hl(sym, "4h", start="2024-01-12", end="2026-05-25")
    out = sig_fn(df, **kw)
    if isinstance(out, tuple):
        le, se = out
    else:
        le, se = out, pd.Series(False, index=df.index)
    fires = le | se
    last_ts = df.index[-1]
    t30 = last_ts - pd.Timedelta(days=30)
    t90 = last_ts - pd.Timedelta(days=90)
    t180 = last_ts - pd.Timedelta(days=180)
    n30 = int(fires[fires.index >= t30].sum())
    n90 = int(fires[fires.index >= t90].sum())
    n180 = int(fires[fires.index >= t180].sum())
    nall = int(fires.sum())
    last_fire = fires[fires].index.max() if fires.any() else None
    rows.append({
        "sleeve": name, "asset": sym, "tot_fires": nall,
        "last_30d": n30, "last_90d": n90, "last_180d": n180,
        "last_fire": str(last_fire) if last_fire is not None else "NEVER",
        "data_end": str(last_ts)
    })
df_out = pd.DataFrame(rows)
df_out.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/a1_v52_fires.csv", index=False)
print(df_out.to_string(index=False))
