"""V7 inspection — confirm panel columns + gate inventory.

Output: lists schema, value distributions, gate fire-rates by (offset, direction).
"""
import os, sys, time
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v3_gated.parquet"
OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v7"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading gated panel")
df = pd.read_parquet(IN)
log(f"rows: {len(df)}, cols: {len(df.columns)}")
print()
print("ALL COLUMNS:")
for c in sorted(df.columns):
    print(f"  {c}: {df[c].dtype}")
print()

g_cols = sorted([c for c in df.columns if c.startswith("g_")])
log(f"gate columns: {len(g_cols)}")
print()
print("GATE FIRE RATES:")
for g in g_cols:
    if df[g].dtype not in ('int64','int32','bool','int8','float64','float32'):
        continue
    fr = df[g].astype(float).mean()
    print(f"  {g:50s}  fire_rate={fr:.3f}  sum={int(df[g].sum())}")

print()
log("offset distribution:")
print(df['fire_offset_s'].value_counts().sort_index())
print()
log("direction distribution:")
print(df['direction'].value_counts())
print()
log("vwap distribution by offset:")
for off in sorted(df.fire_offset_s.unique()):
    sub = df[df.fire_offset_s == off]
    if len(sub):
        print(f"  off={off}: n={len(sub)}, vwap_med={sub['entry_vwap'].median():.3f}, won_mean={sub['won'].mean():.3f}")

print()
log("non-gate feature columns of interest:")
INTEREST = ['rv_60', 'rv_300', 'hurst_h', 'hurst_60', 'mp_skew', 'mp_change',
           'trend_slope_30m', 'f7_rsi_at_ws', 'm1v_state', 'ribbon_slope',
           'rf_dir', 'tr_class', 'tr_stack',
           'lm_stat', 'hawkes_imb', 'vpin', 'vwap_premium',
           'hod_utc', 'minute_of_day',
           ]
for c in INTEREST:
    if c in df.columns:
        s = df[c]
        if s.dtype in ('int64','int32','int8','float64','float32','bool'):
            non_null = s.dropna()
            if len(non_null):
                q = non_null.quantile([0.1, 0.5, 0.9]).values
                print(f"  {c:30s}  coverage={s.notna().mean():.2f}  q10={q[0]:.4f}  q50={q[1]:.4f}  q90={q[2]:.4f}")
            else:
                print(f"  {c}: ALL NaN")
        else:
            print(f"  {c}: dtype={s.dtype}, sample={s.dropna().head(3).tolist()}")
    else:
        print(f"  {c}: NOT PRESENT")

log("done")
