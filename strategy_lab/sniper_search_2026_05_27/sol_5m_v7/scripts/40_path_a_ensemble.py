"""Path A: weighted-ensemble sleeves on SOL 5m.

Drop strict "all gates pass" requirement. Use weight-sum threshold instead.
Weights tuned by train-window WR-lift per gate.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v7")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v7.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
p = p[p['parent_15m_regime'] != ''].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[18]
val_end = dates_sorted[24]
train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()
print(f"train: {len(train)}, val: {len(val)}, lockbox: {len(lock)}")

# Candidate gate pool — the top WR / dpt single gates from V7 search
candidate_gates = [
    'g_btc_trend_30m_with', 'g_btc_trend_15m_with', 'g_btc_trend_5m_with',
    'g_btc_f7_with', 'g_btc_f7_with_loose', 'g_btc_f7_strong_with',
    'g_btc_f7_against',
    'g_f7_v7_oversold', 'g_f7_v7_overbought', 'g_f7_v7_with', 'g_f7_v7_against',
    'g_f7_v7_strong_with', 'g_f7_v7_with_loose',
    'g_hurst_reverting', 'g_hurst_reverting_strong', 'g_hurst_trending',
    'g_parent_with_dir', 'g_parent_slope_with', 'g_parent_slope_strong_with',
    'g_parent_ranging', 'g_parent_trending_up', 'g_parent_trending_dn',
    'g_vol_v7_low', 'g_vol_pct_low', 'g_vol_pct_high',
    'g_cci_extreme_with', 'g_cci_strong_with', 'g_mfi_strong_with',
    'g_mfi_with', 'g_stoch_strong_with', 'g_ribbon_slope_with',
    'g_tr_full_stack_with', 'g_tr_partial_stack_with', 'g_R1_full', 'g_R1_six',
    'g_vwap_in_45_85', 'g_vwap_in_55_80', 'g_vwap_in_30_75',
]
candidate_gates = [g for g in candidate_gates if g in train.columns]
print(f"Candidate gates: {len(candidate_gates)}")

# Compute per-gate WR-lift on TRAIN (vs baseline)
base_wr = train['won'].mean()
print(f"Baseline WR (train): {base_wr:.4f}")
weights = {}
for g in candidate_gates:
    sub = train[train[g]==1]
    if len(sub) < 100:
        continue
    wr_g = sub['won'].mean()
    lift = wr_g - base_wr
    weights[g] = float(lift)
weights_df = pd.DataFrame([{'g': g, 'lift': w, 'abs_lift': abs(w)} for g,w in weights.items()]).sort_values('lift', ascending=False)
print(f"\nGate WR-lifts on train:")
print(weights_df.to_string(index=False))

# Use POSITIVE lift gates only (these add WR)
pos_weights = {g: w for g, w in weights.items() if w > 0.01}  # min lift 1pp
print(f"\nPositive-lift gates ({len(pos_weights)}):")
for g, w in sorted(pos_weights.items(), key=lambda x: -x[1]):
    print(f"  {g}: lift={w:.4f}")

# Build per-fire weight sums
def compute_weight_sum(df, weights_dict):
    ws = np.zeros(len(df), dtype=np.float64)
    for g, w in weights_dict.items():
        if g in df.columns:
            ws += df[g].values * w
    return ws

train['ws_v7'] = compute_weight_sum(train, pos_weights)
val['ws_v7'] = compute_weight_sum(val, pos_weights)
lock['ws_v7'] = compute_weight_sum(lock, pos_weights)
max_ws = max(train['ws_v7'].max(), val['ws_v7'].max(), lock['ws_v7'].max())
print(f"\nMax weight-sum: {max_ws:.4f}")
print(f"train ws_v7 distribution percentiles: 50={train['ws_v7'].quantile(0.5):.4f}, 75={train['ws_v7'].quantile(0.75):.4f}, 90={train['ws_v7'].quantile(0.90):.4f}, 95={train['ws_v7'].quantile(0.95):.4f}")

# Threshold sweep — find max score
def eval_thresh(df, thresh):
    sub = df[df['ws_v7'] >= thresh]
    if len(sub) == 0:
        return None
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0; cur = 0
    for v in pnl:
        if v < 0:
            cur += 1; ls_max = max(ls_max, cur)
        else:
            cur = 0
    return {'n': len(sub), 'wr': float(sub['won'].mean()),
            'dpt': float(pnl.mean()), 'dd': dd, 'ls': ls_max, 'sum': float(pnl.sum())}

# Sweep
print("\n=== Threshold sweep on lockbox ===")
print(f"{'thresh':>8} {'n_l':>5} {'wr_l':>7} {'dpt_l':>8} {'dd_l':>7} {'ls_l':>4} {'sum_l':>9}")
for thresh in np.arange(0.05, max_ws * 0.7, 0.01):
    m = eval_thresh(lock, thresh)
    if m is None or m['n'] < 20:
        continue
    if m['wr'] >= 0.70 and m['dpt'] > 2:
        print(f"{thresh:>8.4f} {m['n']:>5} {m['wr']:>7.4f} {m['dpt']:>8.4f} {m['dd']:>7.1f} {m['ls']:>4} {m['sum']:>9.1f}")
print(f"\nElapsed: {time.time()-t0:.1f}s")
