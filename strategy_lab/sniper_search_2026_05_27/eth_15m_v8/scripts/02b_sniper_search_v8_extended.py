"""V8 sniper search ETH 15m — EXTENDED with full-window-safe vol gate.

Adds g_vol_high_rg (from realized_vol_60m_rg, panel coverage Apr 28 - May 25)
to overcome the staleness of MGF v2 rv_60s panel (cuts off May 22).

Also keeps original V8 sleeves and adds:
  - V7-top variants using g_vol_high_rg instead of g_vol_high
  - Full lock window (May 20-26) sleeves that can fire on May 23-25 too
"""
import os, time, warnings, json
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v8"
LOG = f"{OUT}/_logs"
os.makedirs(LOG, exist_ok=True)

log("loading v8 enriched")
fires = pd.read_parquet(f"{OUT}/eth_15m_enriched_v8.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)

# Build alt vol gates from realized_vol_60m_rg (full window through May 25)
rv = fires.realized_vol_60m_rg
fires['g_vol_high_rg']    = (rv > rv.quantile(0.75)).fillna(False).astype(int)
fires['g_vol_med_rg']     = ((rv > rv.quantile(0.40)) & (rv <= rv.quantile(0.75))).fillna(False).astype(int)
fires['g_vol_extreme_rg'] = (rv > rv.quantile(0.90)).fillna(False).astype(int)
fires['g_vol_low_rg']     = (rv <= rv.quantile(0.40)).fillna(False).astype(int)
log(f"new vol gates from realized_vol_60m_rg:")
for g in ['g_vol_high_rg','g_vol_med_rg','g_vol_extreme_rg','g_vol_low_rg']:
    log(f"  {g}: ones={fires[g].sum()}")

STAKE_NOMINAL = 1.0  # pnl_legacy_usd already in $25 stake
fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date
all_dates = sorted(fires.date.unique())
n_dates = len(all_dates)
i1 = int(n_dates * 0.60); i2 = int(n_dates * 0.80)
TRAIN_DATES = set(all_dates[:i1]); VAL_DATES = set(all_dates[i1:i2]); LOCK_DATES = set(all_dates[i2:])
log(f"v8 split: train={len(TRAIN_DATES)}d val={len(VAL_DATES)}d lock={len(LOCK_DATES)}d full={n_dates}d")
log(f"LOCK dates: {sorted(LOCK_DATES)}")

def hur22_split(df):
    train = (df.date >= pd.to_datetime('2026-05-01').date()) & (df.date < pd.to_datetime('2026-05-14').date())
    val   = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-18').date())
    lock  = (df.date >= pd.to_datetime('2026-05-18').date()) & (df.date <= pd.to_datetime('2026-05-22').date())
    return train, val, lock

def v8_split(df):
    train = df.date.isin(TRAIN_DATES)
    val   = df.date.isin(VAL_DATES)
    lock  = df.date.isin(LOCK_DATES)
    return train, val, lock

def bootstrap_p(df_sub, n_iter=1000, rng=None):
    if rng is None: rng = np.random.default_rng(42)
    if len(df_sub) == 0: return 1.0
    daily = df_sub.groupby('date').pnl_legacy_usd.sum().values * STAKE_NOMINAL
    if len(daily) <= 1: return 1.0
    boot = np.empty(n_iter)
    n_d = len(daily)
    for i in range(n_iter):
        boot[i] = daily[rng.integers(0, n_d, n_d)].sum()
    return float((boot <= 0).mean())

def gated_metrics(df, mask, split_fn):
    sub = df[mask].copy()
    if len(sub) == 0: return None
    out = {'n_full': len(sub), 'wr_full': sub.won.mean()}
    out['sum_pnl_full'] = sub.pnl_legacy_usd.sum() * STAKE_NOMINAL
    out['dpt_full_25'] = sub.pnl_legacy_usd.mean() * STAKE_NOMINAL
    out['days_full'] = sub.date.nunique()
    train_m, val_m, lock_m = split_fn(sub)
    for sn, m in [('train', train_m), ('val', val_m), ('lock', lock_m)]:
        s = sub[m]
        out[f'n_{sn}'] = len(s)
        out[f'wr_{sn}'] = s.won.mean() if len(s) else 0
        out[f'dpt_{sn}_25'] = (s.pnl_legacy_usd.mean() if len(s) else 0) * STAKE_NOMINAL
        out[f'sum_pnl_{sn}'] = s.pnl_legacy_usd.sum() * STAKE_NOMINAL
        out[f'days_{sn}'] = s.date.nunique() if len(s) else 0
    eq = (sub.sort_values('fire_us').pnl_legacy_usd.cumsum() * STAKE_NOMINAL).values
    peak = np.maximum.accumulate(eq); dd = peak - eq
    out['max_dd_25'] = float(dd.max()) if len(dd) else 0.0
    losses = (sub.sort_values('fire_us').won == 0).astype(int).values
    max_s = 0; cur = 0
    for l in losses:
        cur = cur + 1 if l else 0
        if cur > max_s: max_s = cur
    out['loss_streak'] = max_s
    daily = sub.groupby('date').pnl_legacy_usd.sum() * STAKE_NOMINAL
    out['sharpe_daily'] = daily.mean() / daily.std() * np.sqrt(252) if len(daily) > 1 and daily.std() > 0 else 0
    return out

def passes_v8(m):
    if m is None: return False, ["null"]
    fails = []
    if m['n_lock'] < 5: fails.append(f"n_lock<5 ({m['n_lock']})")
    if m['n_full'] > 2000: fails.append(f"n_full>2000 ({m['n_full']})")
    if m['wr_lock'] < 0.65 and m['dpt_lock_25'] < 10: fails.append(f"wr_lock<0.65 & dpt<$10")
    if m['dpt_lock_25'] < 4.0: fails.append(f"dpt_lock<$4")
    if m['max_dd_25'] > 500: fails.append(f"dd>$500")
    if m['loss_streak'] > 14: fails.append(f"streak>14")
    return len(fails) == 0, fails

core4 = ['g_tr_stack_full_with', 'g_above_1h_dailyvwap_with', 'g_offset_early', 'g_vol_high']
core4_rg = ['g_tr_stack_full_with', 'g_above_1h_dailyvwap_with', 'g_offset_early', 'g_vol_high_rg']  # Full-window-safe
v7_top      = core4    + ['g_pw_btc_15m_trend_with']
v7_top_rg   = core4_rg + ['g_pw_btc_15m_trend_with']

# Build the extended stack list
ext = [
    # === Baselines (compare across splits) ===
    ('V8_BASELINE_V7_TOP_HUR22',          v7_top,    'hur22'),
    ('V8_BASELINE_V7_TOP_V8SPLIT',        v7_top,    'v8'),

    # === Full-window-safe V7 winner (vol_high_rg) ===
    ('V8_V7TOP_VOLRG_V8',                 v7_top_rg, 'v8'),
    ('V8_V7TOP_VOLRG_HUR22',              v7_top_rg, 'hur22'),

    # === Path J on full-window-safe core ===
    ('V8_PJ_RG_SOL15M_ALONE',             core4_rg + ['g_pw_sol_15m_trend_with'], 'v8'),
    ('V8_PJ_RG_BTC_SOL_TREND',            core4_rg + ['g_2a_btc_sol_trend_with'], 'v8'),
    ('V8_PJ_RG_3A_TREND_UNANIM',          core4_rg + ['g_3a_trend_unanimity_with'], 'v8'),
    ('V8_PJ_RG_3A_TREND_STRONG',          core4_rg + ['g_3a_trend_unanimity_strong_with'], 'v8'),
    ('V8_PJ_RG_2A_RF_BTC_SOL',            core4_rg + ['g_2a_rf_btc_sol_with'], 'v8'),
    ('V8_PJ_RG_V7TOP_AND_SOL',            v7_top_rg + ['g_pw_sol_15m_trend_with'], 'v8'),
    ('V8_PJ_RG_V7TOP_AND_3A',             v7_top_rg + ['g_3a_trend_unanimity_with'], 'v8'),
    ('V8_PJ_RG_V7TOP_AND_BTC_SOL',        v7_top_rg + ['g_2a_btc_sol_trend_with'], 'v8'),

    # === Path K TOD on full-window-safe core ===
    ('V8_PK_RG_V7TOP_ASIA',               v7_top_rg + ['g_tod_asia'], 'v8'),
    ('V8_PK_RG_V7TOP_EURO',               v7_top_rg + ['g_tod_european'], 'v8'),
    ('V8_PK_RG_V7TOP_US_PM',              v7_top_rg + ['g_tod_us_pm'], 'v8'),
    ('V8_PK_RG_V7TOP_US_EVE',             v7_top_rg + ['g_tod_us_eve'], 'v8'),
    ('V8_PK_RG_CORE_US_PM',               core4_rg + ['g_tod_us_pm'], 'v8'),
    ('V8_PK_RG_CORE_US_EVE',              core4_rg + ['g_tod_us_eve'], 'v8'),
    # Combine 2 TOD buckets (avoid US PM/Eve only)
    # Asia + Euro: 0-13 UTC; US PM + Eve: 13-24
    # Build dynamically:

    # === Path L 1h grandparent on full-window-safe core ===
    ('V8_PL_RG_1H_TREND',                 core4_rg + ['g_gp_1h_trend_with'], 'v8'),
    ('V8_PL_RG_1H_STRONG',                core4_rg + ['g_gp_1h_trend_strong_with'], 'v8'),
    ('V8_PL_RG_1H_EXTREME',               core4_rg + ['g_gp_1h_trend_extreme_with'], 'v8'),
    ('V8_PL_RG_CASCADE_ALIGNED',          core4_rg + ['g_cascade_5m_15m_1h_aligned'], 'v8'),
    ('V8_PL_RG_CASCADE_STRONG',           core4_rg + ['g_cascade_full_strong'], 'v8'),
    ('V8_PL_RG_V7TOP_AND_1H_TREND',       v7_top_rg + ['g_gp_1h_trend_with'], 'v8'),
    ('V8_PL_RG_V7TOP_AND_1H_STRONG',      v7_top_rg + ['g_gp_1h_trend_strong_with'], 'v8'),
    ('V8_PL_RG_V7TOP_AND_CASCADE',        v7_top_rg + ['g_cascade_5m_15m_1h_aligned'], 'v8'),
    ('V8_PL_RG_V7TOP_AND_CASCADE_STR',    v7_top_rg + ['g_cascade_full_strong'], 'v8'),

    # === Path J+K cross ===
    ('V8_JK_RG_V7TOP_3A_US_PM',           v7_top_rg + ['g_3a_trend_unanimity_with','g_tod_us_pm'], 'v8'),
    ('V8_JK_RG_V7TOP_3A_US_EVE',          v7_top_rg + ['g_3a_trend_unanimity_with','g_tod_us_eve'], 'v8'),
    ('V8_JK_RG_V7TOP_SOL_US_PM',          v7_top_rg + ['g_pw_sol_15m_trend_with','g_tod_us_pm'], 'v8'),
    ('V8_JK_RG_V7TOP_2A_US_PM',           v7_top_rg + ['g_2a_btc_sol_trend_with','g_tod_us_pm'], 'v8'),

    # === Path J+L cross ===
    ('V8_JL_RG_V7TOP_3A_1H',              v7_top_rg + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with'], 'v8'),
    ('V8_JL_RG_V7TOP_3A_1H_STRONG',       v7_top_rg + ['g_3a_trend_unanimity_with','g_gp_1h_trend_strong_with'], 'v8'),
    ('V8_JL_RG_V7TOP_SOL_AND_1H',         v7_top_rg + ['g_pw_sol_15m_trend_with','g_gp_1h_trend_with'], 'v8'),
    ('V8_JL_RG_V7TOP_BTC_SOL_1H',         v7_top_rg + ['g_2a_btc_sol_trend_with','g_gp_1h_trend_with'], 'v8'),
    ('V8_JL_RG_BASE_3A_AND_1H_STR',       core4_rg + ['g_3a_trend_unanimity_with','g_gp_1h_trend_strong_with'], 'v8'),

    # === Triple-path J+K+L ===
    ('V8_JKL_RG_V7TOP_3A_1H_US_PM',       v7_top_rg + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with','g_tod_us_pm'], 'v8'),
    ('V8_JKL_RG_V7TOP_SOL_1H_US_PM',      v7_top_rg + ['g_pw_sol_15m_trend_with','g_gp_1h_trend_with','g_tod_us_pm'], 'v8'),
]

# Dedupe
seen = set(); unique = []
for name, gates, sp in ext:
    key = (tuple(sorted(gates)), sp)
    if key in seen: continue
    seen.add(key)
    unique.append((name, gates, sp))
log(f"Total unique extended stacks: {len(unique)}")

results = []
for name, stack, split_kind in unique:
    miss = [g for g in stack if g not in fires.columns]
    if miss:
        log(f"  SKIP {name}: missing {miss}"); continue
    mask = fires[stack].all(axis=1) > 0
    if mask.sum() == 0: continue
    split_fn = v8_split if split_kind == 'v8' else hur22_split
    m = gated_metrics(fires, mask, split_fn)
    if m is None: continue
    sub = fires[mask].copy()
    _, _, lock_m = split_fn(sub)
    p = bootstrap_p(sub[lock_m])
    m['bootstrap_p_lockbox'] = p
    passes, fails = passes_v8(m)
    m['passes_v8'] = passes; m['fails'] = ';'.join(fails)
    m['sleeve_id'] = name; m['gate_stack'] = '&'.join(stack)
    m['split_kind'] = split_kind; m['n_gates'] = len(stack)
    days_lock = max(1, m['days_lock']); days_full = max(1, m['days_full'])
    m['proj_32d']    = m['dpt_lock_25'] * (m['n_lock'] / days_lock) * 32.66 if m['n_lock'] > 0 else 0
    m['proj_full']   = m['dpt_full_25'] * (m['n_full'] / days_full) * 32.66 if m['n_full'] > 0 else 0
    m['proj_honest'] = min(m['proj_32d'], m['proj_full'])
    results.append(m)
    flag = 'PASS' if passes else 'fail'
    log(f"  [{flag}] {name:<42} ({split_kind},{len(stack)}g): n_f={m['n_full']:>4}|n_l={m['n_lock']:>4}|WR_f={m['wr_full']:.3f}|WR_l={m['wr_lock']:.3f}|dpt_f=${m['dpt_full_25']:>5.2f}|dpt_l=${m['dpt_lock_25']:>6.2f}|p={p:.3f}|p32d=${m['proj_32d']:>6.0f}|pF=${m['proj_full']:>6.0f}|pH=${m['proj_honest']:>6.0f}")

df = pd.DataFrame(results).sort_values('proj_honest', ascending=False)
df.to_csv(f"{OUT}/all_candidates_v8_extended.csv", index=False)
log(f"\nTotal: {len(df)} | Passing: {df.passes_v8.sum()}")

# Merge with original
df_orig = pd.read_csv(f"{OUT}/all_candidates_v8.csv")
all_combined = pd.concat([df_orig, df], ignore_index=True)
all_combined.to_csv(f"{OUT}/all_candidates_v8.csv", index=False)
df_pass_all = all_combined[all_combined.passes_v8 == True].copy().sort_values('proj_honest', ascending=False)
df_pass_all.to_csv(f"{OUT}/passing_v8.csv", index=False)
log(f"Combined passing: {len(df_pass_all)}")

# Top 5 by proj_honest
top5 = df_pass_all.head(5)
log("\nTOP 5 V8 by proj_honest:")
for _, r in top5.iterrows():
    log(f"  {r.sleeve_id:<42} | n_full={int(r.n_full):>4} | n_lock={int(r.n_lock):>3} | WR_l={r.wr_lock:.3f} | dpt_l=${r.dpt_lock_25:.2f} | pH=${r.proj_honest:.0f}")

# Write top 5 with V8 brief §5 schema
keep = ['sleeve_id','gate_stack','split_kind','n_gates','n_train','n_val','n_lock','n_full',
        'wr_train','wr_val','wr_lock','wr_full',
        'dpt_train_25','dpt_val_25','dpt_lock_25','dpt_full_25',
        'max_dd_25','loss_streak','sharpe_daily','bootstrap_p_lockbox',
        'proj_32d','proj_full','proj_honest']
rename = {'dpt_train_25':'dpt_25_train','dpt_val_25':'dpt_25_val',
          'dpt_lock_25':'dpt_25_lockbox','dpt_full_25':'dpt_25_full',
          'wr_lock':'wr_lockbox','n_lock':'n_lockbox','sharpe_daily':'sharpe'}
top5_out = top5[keep].rename(columns=rename)
top5_out.to_csv(f"{OUT}/top_5_candidates_v8.csv", index=False)
log("WROTE top_5_candidates_v8.csv (updated)")
log("DONE")
