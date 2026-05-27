"""V7 SOL 15m sniper search.

Approach:
- Build train/val/lockbox split chronologically (60/20/20 of the 33d window)
- Start from V6 winner base: g_hod_european_morning + g_off_60_240 + g_rf_with + g_tr_stack_with + vwap<0.80
  V6 lockbox: n=49, WR 71.4%, $/tr +$4.12, DD $100
- Path C: add cross-asset triggers (BTC/ETH slope, MP skew, regime)
- Path A: weighted ensemble (sum gate-passes; threshold-fire)
- Path G: vol-regime split
- Path H: hurst variants

Output:
  _v7_top_candidates.csv
  _v7_full_search.csv
"""
import os, time, warnings, itertools
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v7"
STAKE = 25.0

log("loading V7 universe")
df = pd.read_parquet(f"{OUT}/sol_15m_v7_universe.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"V7 universe: {len(df):,}")

# Build per-fire PnL at constant $25 (using existing pnl_legacy_usd if present, else compute)
# pnl_legacy_usd was at $25? V3 universe defaults to $25. Verify:
log(f"pnl_legacy_usd sample: {df['pnl_legacy_usd'].head(3).tolist()}")
log(f"won.mean: {df['won'].mean():.3f}; entry_vwap.mean: {df['entry_vwap'].mean():.3f}")
# Reconstruct PnL at $25 per fire to be safe
shares = STAKE / df['entry_vwap']
pnl_won = (1 - df['entry_vwap']) * shares * 0.98
pnl_lost = -df['entry_vwap'] * shares
df['pnl25'] = np.where(df['won']==1, pnl_won, pnl_lost)
# Sanity check vs pnl_legacy_usd
diff = (df['pnl25'] - df['pnl_legacy_usd']).abs().mean()
log(f"pnl25 reconstruction abs diff vs pnl_legacy_usd mean: {diff:.4f} (should be ~0)")

# 3-way split chronological
log("3-way split chronological")
df['fire_dt'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
dt_min, dt_max = df['fire_dt'].min(), df['fire_dt'].max()
total_days = (dt_max - dt_min).total_seconds() / 86400
train_end = dt_min + pd.Timedelta(days=int(total_days*0.6))
val_end = dt_min + pd.Timedelta(days=int(total_days*0.8))
df['split'] = pd.cut(df['fire_dt'], bins=[dt_min - pd.Timedelta(seconds=1), train_end, val_end, dt_max + pd.Timedelta(seconds=1)],
                     labels=['train','val','lockbox'])
log(f"split sizes: {df['split'].value_counts().to_dict()}")
log(f"  train_end={train_end} val_end={val_end} dt_max={dt_max}")

# Define candidate gate stacks for V7
# Base = V6 winner (g_hod_european_morning + g_off_60_240 + g_rf_with + g_tr_stack_with + vwap<0.80)
V6_BASE = ['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with']
V6_VWAP = 0.80

# Cross-asset add-on gates
CROSS_GATES = [
    'g_BTC_slope_with', 'g_BTC_slope_strong_with',
    'g_ETH_slope_with', 'g_ETH_slope_strong_with',
    'g_BTC_mp_skew_with', 'g_BTC_mp_skew_strong_with',
    'g_ETH_mp_skew_with', 'g_ETH_mp_skew_strong_with',
    'g_BTC_regime_trend_with', 'g_ETH_regime_trend_with',
    'g_BTC_regime_trend_either', 'g_ETH_regime_trend_either',
    'g_BTC_tr_stack_with', 'g_ETH_tr_stack_with',
    'g_BTC_adx_strong', 'g_ETH_adx_strong',
    'g_xa_btc_eth_slope_unanimity_with', 'g_xa_btc_eth_regime_trend_with',
    'g_xa_3asset_mp_skew_with',
    'g_BTC_vol_high', 'g_ETH_vol_high',
    'g_BTC_vol_low', 'g_ETH_vol_low',
]

VOL_HURST_GATES = [
    'g_rv_high', 'g_rv_low', 'g_rv_very_high', 'g_rv_very_low',
    'g_vol_regime_high', 'g_vol_regime_low', 'g_vol_regime_med',
    'g_hurst_strong_trending', 'g_hurst_reverting', 'g_hurst_mid_trending', 'g_hurst_50_plus',
]

# Single-gate add-on test: add ONE cross-asset gate to V6 base + vwap<0.80, see effect
def evaluate(mask, label, base_n_train=None):
    """Compute metrics on the masked subset across train/val/lockbox."""
    sub = df[mask].copy()
    if len(sub) < 5:
        return None
    out = {'sleeve': label, 'n_total': len(sub)}
    for s in ['train','val','lockbox']:
        ss = sub[sub['split']==s]
        if len(ss) > 0:
            out[f'n_{s}'] = len(ss)
            out[f'wr_{s}'] = ss['won'].mean()
            out[f'dpt_{s}'] = ss['pnl25'].mean()
            out[f'sum_{s}'] = ss['pnl25'].sum()
        else:
            out[f'n_{s}'] = 0
            out[f'wr_{s}'] = np.nan
            out[f'dpt_{s}'] = np.nan
            out[f'sum_{s}'] = 0
    # DD and loss streak on lockbox
    lb = sub[sub['split']=='lockbox'].sort_values('fire_us')
    cum = lb['pnl25'].cumsum().values if len(lb) > 0 else np.array([0])
    out['dd_lockbox'] = (np.maximum.accumulate(cum) - cum).max() if len(cum) > 0 else 0
    # Loss streak lockbox
    losses = (lb['won']==0).astype(int).values if len(lb) > 0 else np.array([0])
    max_streak, cur = 0, 0
    for x in losses:
        if x == 1: cur += 1; max_streak = max(max_streak, cur)
        else: cur = 0
    out['loss_streak_lockbox'] = max_streak
    # Sharpe (daily)
    if len(lb) > 1:
        lb_per_day = lb.groupby(lb['fire_dt'].dt.date)['pnl25'].sum()
        out['sharpe_lockbox'] = (lb_per_day.mean() / lb_per_day.std() * np.sqrt(252)) if lb_per_day.std() > 0 else 0
    else:
        out['sharpe_lockbox'] = 0
    return out

def gate_mask(stack, df=df):
    """Build AND-mask over all gates in stack. NaN -> treat as fail (0)."""
    m = pd.Series(True, index=df.index)
    for g in stack:
        if g not in df.columns:
            return pd.Series(False, index=df.index)
        v = df[g].fillna(0).astype(float)
        m = m & (v >= 0.5)
    return m

# Base V6 mask + vwap filter
base_mask = gate_mask(V6_BASE) & (df['entry_vwap'] < V6_VWAP)
base_eval = evaluate(base_mask, "V6_BASE_g_hod_eu_off60_240_rf_trstack_vwap_lt80")
log(f"V6 BASE eval: n_lock={base_eval['n_lockbox']}, wr_lock={base_eval['wr_lockbox']:.3f}, dpt_lock={base_eval['dpt_lockbox']:.2f}, dd={base_eval['dd_lockbox']:.0f}")

# === Phase 1: single cross-asset add-on to V6 base ===
log("=== Phase 1: single cross-asset gate add-on ===")
results = [base_eval]
for g in CROSS_GATES + VOL_HURST_GATES:
    if g not in df.columns:
        continue
    stack = V6_BASE + [g]
    m = gate_mask(stack) & (df['entry_vwap'] < V6_VWAP)
    e = evaluate(m, f"V6+{g}")
    if e:
        results.append(e)

# Also try base without HoD restriction (just to see if HoD is doing all the work)
m_no_hod = gate_mask([g for g in V6_BASE if g != 'g_hod_european_morning']) & (df['entry_vwap'] < V6_VWAP)
for g in CROSS_GATES + VOL_HURST_GATES:
    if g not in df.columns: continue
    stack = ['g_off_60_240','g_rf_with','g_tr_stack_with', g]
    m = gate_mask(stack) & (df['entry_vwap'] < V6_VWAP)
    e = evaluate(m, f"NOHOD_{g}")
    if e and e['n_lockbox'] >= 20:
        results.append(e)

# Pairs of cross-asset gates added to V6 base
log("=== Phase 2: pairs of cross-asset gates ===")
xa_subset = [g for g in CROSS_GATES if g in df.columns and 0.2 <= df[g].mean() <= 0.85]
log(f"  xa_subset for pairs ({len(xa_subset)}): {xa_subset}")
for g1, g2 in itertools.combinations(xa_subset, 2):
    stack = V6_BASE + [g1, g2]
    m = gate_mask(stack) & (df['entry_vwap'] < V6_VWAP)
    e = evaluate(m, f"V6+{g1}+{g2}")
    if e and e['n_lockbox'] >= 15:
        results.append(e)

# Triples
log("=== Phase 3: triples ===")
for g1, g2, g3 in itertools.combinations(xa_subset, 3):
    stack = V6_BASE + [g1, g2, g3]
    m = gate_mask(stack) & (df['entry_vwap'] < V6_VWAP)
    e = evaluate(m, f"V6+{g1}+{g2}+{g3}")
    if e and e['n_lockbox'] >= 10:
        results.append(e)

# === Phase 4: Vol regime split — test V6 base in each vol regime separately ===
log("=== Phase 4: vol regime split ===")
for vg in ['g_BTC_vol_high','g_BTC_vol_low','g_ETH_vol_high','g_ETH_vol_low','g_rv_high','g_rv_low','g_vol_regime_high','g_vol_regime_low','g_vol_regime_med']:
    if vg not in df.columns: continue
    # V6 + vol gate, no vwap filter
    m_a = gate_mask(V6_BASE + [vg])
    e_a = evaluate(m_a, f"V6+{vg}_no_vwap")
    if e_a and e_a['n_lockbox'] >= 15:
        results.append(e_a)
    # V6 + vol gate + vwap<0.80
    m_b = gate_mask(V6_BASE + [vg]) & (df['entry_vwap'] < V6_VWAP)
    e_b = evaluate(m_b, f"V6+{vg}_vwap_lt80")
    if e_b and e_b['n_lockbox'] >= 15:
        results.append(e_b)

# === Phase 5: Hurst variants stacked on V6 ===
log("=== Phase 5: hurst variants ===")
for hg in ['g_hurst_reverting','g_hurst_mid_trending','g_hurst_50_plus']:
    if hg not in df.columns: continue
    m = gate_mask(V6_BASE + [hg]) & (df['entry_vwap'] < V6_VWAP)
    e = evaluate(m, f"V6+{hg}_vwap_lt80")
    if e and e['n_lockbox'] >= 15:
        results.append(e)

# === Phase 6: Path A — weighted ensemble ===
# Build a conviction score from a basket of cross-asset + V6 atoms; fire when score >= threshold
log("=== Phase 6: Path A weighted ensemble ===")
ENSEMBLE_GATES = [
    ('g_rf_with', 1.0),
    ('g_tr_stack_with', 1.5),
    ('g_off_60_240', 0.5),
    ('g_hod_european_morning', 1.0),
    ('g_BTC_slope_with', 1.0),
    ('g_ETH_slope_with', 0.8),
    ('g_BTC_mp_skew_with', 0.7),
    ('g_ETH_mp_skew_with', 0.5),
    ('g_xa_btc_eth_slope_unanimity_with', 1.2),
    ('g_BTC_tr_stack_with', 0.8),
    ('g_ETH_tr_stack_with', 0.6),
    ('g_ribbon_agrees', 0.5),
    ('g_markov_with', 0.4),
    ('g_mp_no_extreme', 0.4),
]
g_sum = pd.Series(0.0, index=df.index)
g_max = 0.0
for g, w in ENSEMBLE_GATES:
    if g not in df.columns: continue
    v = df[g].fillna(0).astype(float).clip(0, 1)
    g_sum = g_sum + v * w
    g_max += w
df['ensemble_score'] = g_sum
df['ensemble_score_norm'] = g_sum / g_max
log(f"  ensemble_score range: [{g_sum.min():.2f}, {g_sum.max():.2f}] (max={g_max:.2f})")

# Thresholds: sweep
for thr in [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
    m = (df['ensemble_score_norm'] >= thr) & (df['entry_vwap'] < V6_VWAP)
    e = evaluate(m, f"ENSEMBLE_norm{thr}_vwap_lt80")
    if e and e['n_lockbox'] >= 15:
        results.append(e)

# Vol-regime conditional ensemble
for vg, thr_extra in [('g_rv_high', 0.05), ('g_rv_low', 0.05)]:
    if vg not in df.columns: continue
    for thr in [0.50, 0.55, 0.60, 0.65]:
        m = (df['ensemble_score_norm'] >= thr) & (df[vg].fillna(0).astype(int)==1) & (df['entry_vwap'] < V6_VWAP)
        e = evaluate(m, f"ENSEMBLE_norm{thr}_{vg}_vwap_lt80")
        if e and e['n_lockbox'] >= 10:
            results.append(e)

# Convert results to DataFrame
rdf = pd.DataFrame(results)
rdf = rdf.sort_values('dpt_lockbox', ascending=False)
rdf.to_csv(f"{OUT}/_v7_full_search.csv", index=False)
log(f"WROTE _v7_full_search.csv ({len(rdf)} rows)")

# Filter to V7 profile: dpt_lockbox >= 4, wr_lockbox >= 0.55, n_lockbox >= 15, dd_lockbox <= 500, loss_streak <= 14
profile = rdf[
    (rdf['n_lockbox'] >= 15) &
    (rdf['wr_lockbox'] >= 0.55) &
    (rdf['dpt_lockbox'] >= 4.0) &
    (rdf['dd_lockbox'] <= 500) &
    (rdf['loss_streak_lockbox'] <= 14) &
    (rdf['n_total'] >= 30)
].copy()
profile = profile.sort_values('dpt_lockbox', ascending=False)
log(f"V7 profile-pass: {len(profile)} candidates")

# Also extract "high $/tr" winners regardless of WR (>= $5 dpt)
high_dpt = rdf[(rdf['n_lockbox'] >= 15) & (rdf['dpt_lockbox'] >= 5.0)].copy()
high_dpt = high_dpt.sort_values('dpt_lockbox', ascending=False)
log(f"V7 high-dpt (>=$5): {len(high_dpt)} candidates")

# Composite metric: dpt × sqrt(n)
rdf['composite'] = rdf['dpt_lockbox'] * np.sqrt(rdf['n_lockbox'].clip(lower=0))
top_composite = rdf[rdf['n_lockbox'] >= 15].sort_values('composite', ascending=False).head(20).copy()

# Save tops
profile.head(20).to_csv(f"{OUT}/_v7_profile_pass.csv", index=False)
top_composite.to_csv(f"{OUT}/_v7_top_composite.csv", index=False)

print("\n=== TOP 10 by dpt_lockbox (n>=15, profile pass) ===")
if len(profile) > 0:
    print(profile.head(10)[['sleeve','n_train','n_val','n_lockbox','wr_train','wr_val','wr_lockbox','dpt_train','dpt_val','dpt_lockbox','dd_lockbox','loss_streak_lockbox','sharpe_lockbox']].to_string())
else:
    print("  NONE")

print("\n=== TOP 10 by composite (dpt*sqrt(n)) ===")
print(top_composite.head(10)[['sleeve','n_lockbox','wr_lockbox','dpt_lockbox','composite','dd_lockbox','loss_streak_lockbox','sharpe_lockbox']].to_string())

print("\n=== V6 BASE for reference ===")
print(pd.DataFrame([base_eval])[['sleeve','n_lockbox','wr_lockbox','dpt_lockbox','dd_lockbox','loss_streak_lockbox','sharpe_lockbox']].to_string())
log("DONE")
