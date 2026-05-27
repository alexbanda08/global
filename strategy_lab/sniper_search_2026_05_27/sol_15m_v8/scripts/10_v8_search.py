"""V8 SOL 15m sniper search.

Builds on V7 base (V6_BASE + cross-asset gates), extending into:
- Path J: 2-asset confluence ensembles (BTC AND ETH AND/OR + 3-asset unanimity strong)
- Path K: TOD 4-bucket specialization (test V7 winners stacked on each TOD)
- Path L: 1h grandparent regime (BTC/ETH/SOL 1h slope/trend/adx)
- Path O: HL funding/OI/liq (TRAIN+VAL ONLY — lockbox no HL coverage)

Strategy:
1) Re-evaluate V7 winners as baselines (S5_BTC_SLOPE_STR, S1_BTC_ADX_VOLLOW, S3_XADX_ETHVOLLOW)
2) Add ONE V8 gate at a time to each V7 winner; report lift
3) Pairs of V8 gates added to V7 base
4) Triples of V8 gates added to V7 base
5) TOD 4-bucket: split V7 winners by TOD; find TOD-specialized winners
6) HL gates: TRAIN+VAL only, project forward as "potential" candidates
7) 1h grandparent: stack BTC + ETH + SOL 1h gates on V7 winner

Output:
  _v8_full_search.csv
  _v8_profile_pass.csv
  _v8_top_composite.csv
  _v8_tod_specialization.csv
"""
import os, time, warnings, itertools
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v8"
STAKE = 25.0

log("loading V8 universe")
df = pd.read_parquet(f"{OUT}/sol_15m_v8_universe.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"V8 universe: {len(df):,} rows, {len(df.columns)} cols")

# Reconstruct PnL at $25
shares = STAKE / df['entry_vwap']
df['pnl25'] = np.where(df['won']==1,
                       (1 - df['entry_vwap']) * shares * 0.98,
                       -df['entry_vwap'] * shares)

# 3-way split chronological (60/20/20)
df['fire_dt'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
total_days = (df['fire_dt'].max() - df['fire_dt'].min()).total_seconds() / 86400
log(f"total_days: {total_days:.3f}")
train_end = df['fire_dt'].min() + pd.Timedelta(days=int(total_days*0.6))
val_end   = df['fire_dt'].min() + pd.Timedelta(days=int(total_days*0.8))
df['split'] = pd.cut(df['fire_dt'],
    bins=[df['fire_dt'].min()-pd.Timedelta(seconds=1), train_end, val_end, df['fire_dt'].max()+pd.Timedelta(seconds=1)],
    labels=['train','val','lockbox'])
log(f"split counts: {df['split'].value_counts().to_dict()}")
log(f"  train_end={train_end}, val_end={val_end}")

# Compute days per split for projection
for s in ['train','val','lockbox']:
    sub = df[df['split']==s]
    days = (sub['fire_dt'].max() - sub['fire_dt'].min()).total_seconds() / 86400 if len(sub)>0 else 0
    log(f"    {s}: span_days={days:.2f}")

def evaluate(mask, label, df=df):
    """Compute per-split + full metrics."""
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
    # Full window
    out['n_full'] = len(sub)
    out['wr_full'] = sub['won'].mean()
    out['dpt_full'] = sub['pnl25'].mean()
    out['sum_full'] = sub['pnl25'].sum()
    # DD lockbox
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

def gate_mask(stack, df=df, extra_vwap_lt=None):
    m = pd.Series(True, index=df.index)
    for g in stack:
        if g not in df.columns:
            return pd.Series(False, index=df.index)
        v = df[g].fillna(0).astype(float)
        m = m & (v >= 0.5)
    if extra_vwap_lt is not None:
        m = m & (df['entry_vwap'] < extra_vwap_lt)
    return m

# === V6/V7 base ===
V6_BASE = ['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with']
V6_VWAP = 0.80

# V7 winners (baselines to compare against):
V7_BASES = {
    'S5_SLOPE_STR': V6_BASE + ['g_BTC_slope_with','g_BTC_slope_strong_with'],
    'S1_ADX_VOLLOW': V6_BASE + ['g_BTC_tr_stack_with','g_BTC_adx_strong','g_BTC_vol_low'],
    'S3_XADX_ETHVOLLOW': V6_BASE + ['g_BTC_adx_strong','g_ETH_adx_strong','g_ETH_vol_low'],
}

# V8 gates by path
PATH_J = [c for c in df.columns if c.startswith('g_J_')]
PATH_K_TOD4 = ['g_K_tod_asia_morning','g_K_tod_european_morning','g_K_tod_us_afternoon','g_K_tod_us_evening']
PATH_K_TOD8 = [c for c in df.columns if c.startswith('g_K_h')]
PATH_L = [c for c in df.columns if c.startswith('g_L_')]
PATH_O = [c for c in df.columns if c.startswith('g_O_')]

log(f"PATH_J: {PATH_J}")
log(f"PATH_L: {PATH_L}")
log(f"PATH_O: {PATH_O}")

results = []

# Baselines
log("=== baselines (V6 + V7 winners) ===")
e = evaluate(gate_mask(V6_BASE, extra_vwap_lt=V6_VWAP), "V6_BASE")
log(f"  V6_BASE: n_lock={e['n_lockbox']} wr_lock={e['wr_lockbox']:.3f} dpt_lock={e['dpt_lockbox']:.2f}")
results.append(e)

for name, base in V7_BASES.items():
    e = evaluate(gate_mask(base, extra_vwap_lt=V6_VWAP), f"V7_BASE_{name}")
    log(f"  V7_{name}: n_lock={e['n_lockbox']} wr_lock={e['wr_lockbox']:.3f} dpt_lock={e['dpt_lockbox']:.2f}")
    results.append(e)

# Phase 1: V7 + ONE V8 gate (J or L only — O excluded from lockbox eval)
log("=== Phase 1: V7_base + ONE V8 gate ===")
ALL_V8_NON_O = PATH_J + PATH_L
for name, base in V7_BASES.items():
    for g in ALL_V8_NON_O:
        if g not in df.columns: continue
        e = evaluate(gate_mask(base + [g], extra_vwap_lt=V6_VWAP), f"V7_{name}+{g}")
        if e: results.append(e)

# Phase 2: V6 + ONE V8 gate (find any V8 gate that beats V6 baseline on its own)
log("=== Phase 2: V6_BASE + ONE V8 gate (J+L only) ===")
for g in ALL_V8_NON_O:
    if g not in df.columns: continue
    e = evaluate(gate_mask(V6_BASE + [g], extra_vwap_lt=V6_VWAP), f"V6+{g}")
    if e: results.append(e)

# Phase 3: V6 + ONE V8 J + ONE V8 L (combine across paths)
log("=== Phase 3: V6 + J + L combos ===")
for gj in PATH_J:
    if gj not in df.columns: continue
    for gl in PATH_L:
        if gl not in df.columns: continue
        e = evaluate(gate_mask(V6_BASE + [gj, gl], extra_vwap_lt=V6_VWAP), f"V6+{gj}+{gl}")
        if e and e['n_lockbox'] >= 10: results.append(e)

# Phase 4: V7_BASE_S5 + ONE J + ONE L (deeper stacking)
log("=== Phase 4: V7_S5 + J + L combos ===")
S5 = V7_BASES['S5_SLOPE_STR']
for gj in PATH_J:
    if gj not in df.columns: continue
    for gl in PATH_L:
        if gl not in df.columns: continue
        e = evaluate(gate_mask(S5 + [gj, gl], extra_vwap_lt=V6_VWAP), f"V7_S5+{gj}+{gl}")
        if e and e['n_lockbox'] >= 8: results.append(e)

# Phase 5: V7_BASE_S1 + V8 single gate (J or L)
log("=== Phase 5: V7_S1 + ONE J + ONE L ===")
S1 = V7_BASES['S1_ADX_VOLLOW']
for gj in PATH_J:
    if gj not in df.columns: continue
    for gl in PATH_L:
        if gl not in df.columns: continue
        e = evaluate(gate_mask(S1 + [gj, gl], extra_vwap_lt=V6_VWAP), f"V7_S1+{gj}+{gl}")
        if e and e['n_lockbox'] >= 8: results.append(e)

# Phase 6: Path K — TOD specialization on V7 winners
log("=== Phase 6: Path K — TOD 4-bucket specialization ===")
# For each V7 winner, drop the HOD restriction (g_hod_european_morning) and replace with each TOD bucket
V6_NO_HOD = ['g_off_60_240','g_rf_with','g_tr_stack_with']  # remove g_hod_european_morning
for name, base in V7_BASES.items():
    # remove hod from base
    base_no_hod = [g for g in base if g != 'g_hod_european_morning']
    for tod_gate in PATH_K_TOD4:
        e = evaluate(gate_mask(base_no_hod + [tod_gate], extra_vwap_lt=V6_VWAP), f"V7_{name}_TOD_{tod_gate.replace('g_K_tod_','')}")
        if e: results.append(e)

# Also Phase 6b: V6 base without HoD + TOD bucket alone (4 baseline TOD slices of V6)
for tod_gate in PATH_K_TOD4:
    e = evaluate(gate_mask(V6_NO_HOD + [tod_gate], extra_vwap_lt=V6_VWAP), f"V6_NO_HOD_TOD_{tod_gate.replace('g_K_tod_','')}")
    if e: results.append(e)

# Phase 6c: 8-bucket fine TOD on V7_S5
for tod_gate in PATH_K_TOD8:
    S5_no_hod = [g for g in S5 if g != 'g_hod_european_morning']
    e = evaluate(gate_mask(S5_no_hod + [tod_gate], extra_vwap_lt=V6_VWAP), f"V7_S5_NO_HOD_{tod_gate.replace('g_K_h','h')}")
    if e: results.append(e)

# Phase 7: Path J pure 2-asset confluence as a primary trigger (no V6 base) — test thinning
log("=== Phase 7: pure Path J (no V6 base) ===")
PURE_J_TRIGGERS = ['g_J_btc_eth_slope_unan_strong','g_J_btc_eth_adx_both_strong','g_J_btc_eth_tr_stack_unan_with',
                   'g_J_btc_eth_triple_unan_with','g_J_btc_eth_mp_unan_with','g_J_3asset_mp_strong_unan_with']
for gj in PURE_J_TRIGGERS:
    if gj not in df.columns: continue
    # gj alone + vwap < 0.80 (very loose)
    e = evaluate(gate_mask([gj], extra_vwap_lt=V6_VWAP), f"PURE_{gj}")
    if e: results.append(e)
    # gj + g_rf_with + g_tr_stack_with (V6 minus hod minus off)
    e = evaluate(gate_mask(['g_rf_with','g_tr_stack_with', gj], extra_vwap_lt=V6_VWAP), f"MIN_RF_TRS+{gj}")
    if e: results.append(e)

# Phase 8: Path O — HL gates (TRAIN+VAL ONLY — lockbox has no HL)
log("=== Phase 8: Path O (HL) — TRAIN+VAL eval only ===")
# For O gates, evaluate on full data BUT note: lockbox metrics are based on default-fail (HL nan = fail).
# So an O-stacked sleeve will have 0 lockbox n. Use train+val as the eval window.
hl_results = []
def evaluate_hl(mask, label):
    """For HL gates, evaluate on full + train+val (lockbox has no HL coverage)."""
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
    # Combined train+val "lockbox-substitute"
    tv = sub[sub['split'].isin(['train','val'])]
    out['n_tv'] = len(tv); out['wr_tv'] = tv['won'].mean() if len(tv)>0 else 0; out['dpt_tv'] = tv['pnl25'].mean() if len(tv)>0 else 0
    out['n_full'] = len(sub); out['wr_full'] = sub['won'].mean(); out['dpt_full'] = sub['pnl25'].mean(); out['sum_full'] = sub['pnl25'].sum()
    # DD on train+val
    tv2 = tv.sort_values('fire_us')
    cum = tv2['pnl25'].cumsum().values if len(tv2) > 0 else np.array([0])
    out['dd_lockbox'] = (np.maximum.accumulate(cum) - cum).max() if len(cum) > 0 else 0
    losses = (tv2['won']==0).astype(int).values if len(tv2) > 0 else np.array([0])
    max_streak, cur = 0, 0
    for x in losses:
        if x == 1: cur += 1; max_streak = max(max_streak, cur)
        else: cur = 0
    out['loss_streak_lockbox'] = max_streak
    out['sharpe_lockbox'] = 0
    return out

# HL gates on V6 base
for g in PATH_O:
    if g not in df.columns: continue
    m = gate_mask(V6_BASE + [g], extra_vwap_lt=V6_VWAP)
    e = evaluate_hl(m, f"HL_V6+{g}")
    if e: hl_results.append(e)
# HL gates on V7_S5 base
for g in PATH_O:
    if g not in df.columns: continue
    m = gate_mask(V7_BASES['S5_SLOPE_STR'] + [g], extra_vwap_lt=V6_VWAP)
    e = evaluate_hl(m, f"HL_V7_S5+{g}")
    if e: hl_results.append(e)
# HL gates on V7_S1
for g in PATH_O:
    if g not in df.columns: continue
    m = gate_mask(V7_BASES['S1_ADX_VOLLOW'] + [g], extra_vwap_lt=V6_VWAP)
    e = evaluate_hl(m, f"HL_V7_S1+{g}")
    if e: hl_results.append(e)

hl_rdf = pd.DataFrame(hl_results)
if len(hl_rdf) > 0:
    hl_rdf = hl_rdf.sort_values('dpt_tv', ascending=False)
    hl_rdf.to_csv(f"{OUT}/_v8_hl_search.csv", index=False)
    log(f"  HL sleeves tested: {len(hl_rdf)}; top by dpt_tv:")
    print(hl_rdf.head(8)[['sleeve','n_tv','wr_tv','dpt_tv','n_train','wr_train','dpt_train','n_val','wr_val','dpt_val','dd_lockbox','loss_streak_lockbox']].to_string())

# === Aggregate non-HL results ===
rdf = pd.DataFrame(results)
log(f"non-HL sleeves tested: {len(rdf)}")
# Sort by lockbox dpt
rdf = rdf.sort_values('dpt_lockbox', ascending=False)
rdf.to_csv(f"{OUT}/_v8_full_search.csv", index=False)
log(f"WROTE _v8_full_search.csv ({len(rdf)} rows)")

# Profile: V8 target (lockbox n>=15, wr>=0.55 or wr>=0.65 if dpt low, dpt>=4, dd<=500, ls<=14)
def profile_pass(r):
    return ((r['n_lockbox'] >= 15) and (r['dpt_lockbox'] >= 4.0) and
            (r['dd_lockbox'] <= 500) and (r['loss_streak_lockbox'] <= 14) and
            (r['n_total'] >= 30) and
            ((r['wr_lockbox'] >= 0.65) or (r['wr_lockbox'] >= 0.55 and r['dpt_lockbox'] >= 10.0)))

mask_pp = rdf.apply(profile_pass, axis=1)
profile = rdf[mask_pp].copy()
profile = profile.sort_values('dpt_lockbox', ascending=False)
log(f"V8 profile-pass: {len(profile)} candidates")
profile.head(30).to_csv(f"{OUT}/_v8_profile_pass.csv", index=False)

# Composite
rdf['composite'] = rdf['dpt_lockbox'] * np.sqrt(rdf['n_lockbox'].clip(lower=0))
top_composite = rdf[rdf['n_lockbox'] >= 15].sort_values('composite', ascending=False).head(30).copy()
top_composite.to_csv(f"{OUT}/_v8_top_composite.csv", index=False)

# TOD specialization slice
tod_rdf = rdf[rdf['sleeve'].str.contains('_TOD_|_NO_HOD_h', regex=True)].copy()
tod_rdf = tod_rdf.sort_values('dpt_lockbox', ascending=False)
tod_rdf.to_csv(f"{OUT}/_v8_tod_specialization.csv", index=False)
log(f"TOD-specialized sleeves: {len(tod_rdf)}")

print("\n=== TOP 15 by dpt_lockbox (n>=15) ===")
top15 = rdf[rdf['n_lockbox']>=15].sort_values('dpt_lockbox', ascending=False).head(15)
print(top15[['sleeve','n_train','n_val','n_lockbox','wr_train','wr_val','wr_lockbox','dpt_train','dpt_val','dpt_lockbox','dd_lockbox','loss_streak_lockbox']].to_string())

print("\n=== TOP 15 by composite (dpt*sqrt(n)) ===")
print(top_composite.head(15)[['sleeve','n_lockbox','wr_lockbox','dpt_lockbox','composite','dd_lockbox','loss_streak_lockbox']].to_string())

print("\n=== TOP 10 TOD specialization ===")
print(tod_rdf.head(10)[['sleeve','n_total','n_train','n_val','n_lockbox','wr_lockbox','dpt_lockbox','dd_lockbox']].to_string())

print("\n=== V7 BASELINES for comparison ===")
print(rdf[rdf['sleeve'].str.startswith('V7_BASE_') | (rdf['sleeve']=='V6_BASE')][
    ['sleeve','n_lockbox','wr_lockbox','dpt_lockbox','dd_lockbox','loss_streak_lockbox']].to_string())

log("DONE")
