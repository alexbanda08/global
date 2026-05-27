"""V8 sniper search ETH 15m — Paths J/K/L per V8 brief.

V7 baseline (for reference):
  V7_PI_S1_BTC_15M_TREND = g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early
                          & g_vol_high & g_pw_btc_15m_trend_with
  -> n_lock=21, WR_lock=95.2%, $/tr=$12.28, $258 lockbox PnL, 32.7d proj $2,106

V8 brief §0: USE FULL 32.7d WINDOW. 3-way split: 60% train / 20% val / 20% lock.
  - For sleeves using only V7-embedded features + V8 J/K/L features, use full panel intersection.
  - SOL trend slope panel coverage = Apr 28 → May 25 (28d); 1h grandparent = full.
  - Report n_full / WR_full / $/tr_full alongside lockbox metrics.

V8 explore priorities (per brief §6 for ETH 15m):
  Path J (2-asset confluence): BTC+SOL trend → ETH; 3-asset unanimity
  Path K (TOD specialization): asia/european/us_pm/us_eve buckets
  Path L (1h grandparent cascade): 5m + 15m + 1h all aligned
  Path M (offset=0): N/A — minimum offset in v3 fires is 60s

Stake: constant $25.
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
log(f"shape: {fires.shape}")
log(f"date range: {pd.to_datetime(fires.fire_us.min(), unit='us')} -> {pd.to_datetime(fires.fire_us.max(), unit='us')}")

mean_abs_pnl = fires.pnl_legacy_usd.abs().mean()
STAKE_NOMINAL = 1.0 if mean_abs_pnl > 1 else 25.0
log(f"mean |pnl_legacy_usd|: {mean_abs_pnl:.4f} | STAKE_NOMINAL = {STAKE_NOMINAL}")

fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date
all_dates = sorted(fires.date.unique())
n_dates = len(all_dates)
log(f"unique dates: {n_dates} | first {all_dates[0]} last {all_dates[-1]}")

# 3-way split per V8 brief §0: 60% train / 20% val / 20% lock by DATE ORDER on full window
TRAIN_END_IDX = int(n_dates * 0.60)
VAL_END_IDX   = int(n_dates * 0.80)
TRAIN_DATES = set(all_dates[:TRAIN_END_IDX])
VAL_DATES   = set(all_dates[TRAIN_END_IDX:VAL_END_IDX])
LOCK_DATES  = set(all_dates[VAL_END_IDX:])
DAYS_TRAIN = len(TRAIN_DATES); DAYS_VAL = len(VAL_DATES); DAYS_LOCK = len(LOCK_DATES)
DAYS_FULL  = n_dates
log(f"split: train={DAYS_TRAIN}d val={DAYS_VAL}d lock={DAYS_LOCK}d full={DAYS_FULL}d")

# Also keep HUR22 cohort for V7 baseline replication
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
        idx = rng.integers(0, n_d, n_d)
        boot[i] = daily[idx].sum()
    return (boot <= 0).mean()

def gated_metrics(df, mask, split_fn=v8_split):
    sub = df[mask].copy()
    if len(sub) == 0:
        return None
    out = {'n_full': len(sub), 'wr_full': sub.won.mean()}
    out['sum_pnl_full'] = sub.pnl_legacy_usd.sum() * STAKE_NOMINAL
    out['dpt_full_25'] = (sub.pnl_legacy_usd.mean() if len(sub) else 0) * STAKE_NOMINAL
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
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
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
    if m is None: return False, ["null_metrics"]
    fails = []
    if m['n_lock'] < 5: fails.append(f"n_lock<5 ({m['n_lock']})")
    if m['n_full'] > 2000: fails.append(f"n_full>2000 ({m['n_full']})")
    if m['wr_lock'] < 0.65 and m['dpt_lock_25'] < 10: fails.append(f"wr_lock<0.65 & dpt<$10")
    if m['dpt_lock_25'] < 4.0: fails.append(f"dpt_lock<$4")
    if m['max_dd_25'] > 500: fails.append(f"dd>$500")
    if m['loss_streak'] > 14: fails.append(f"streak>14")
    return len(fails) == 0, fails

# Core base from V6/V7 winner
core4 = ['g_tr_stack_full_with', 'g_above_1h_dailyvwap_with', 'g_offset_early', 'g_vol_high']
v7_top = core4 + ['g_pw_btc_15m_trend_with']  # V7 #1 winner

# ============================================================
# PATH J — 2-asset confluence
# ============================================================
path_j = [
    # V7 baseline replicated under V8 split
    ('V8_BASELINE_V7_TOP',                   v7_top, 'v8'),
    ('V8_BASELINE_V7_TOP_HUR22',             v7_top, 'hur22'),
    # 2-asset SOL trend ALONE (replace BTC trend with SOL trend)
    ('V8_PJ_SOL15M_ALONE',                   core4 + ['g_pw_sol_15m_trend_with'], 'v8'),
    ('V8_PJ_SOL15M_STRONG',                  core4 + ['g_pw_sol_15m_trend_strong_with'], 'v8'),
    # BTC+SOL trend confluence (Path J primary for ETH)
    ('V8_PJ_BTC_SOL_TREND',                  core4 + ['g_2a_btc_sol_trend_with'], 'v8'),
    ('V8_PJ_BTC_AND_SOL_TREND_SEP',          core4 + ['g_pw_btc_15m_trend_with','g_pw_sol_15m_trend_with'], 'v8'),
    # 3-asset trend unanimity (BTC+SOL+ETH all align)
    ('V8_PJ_3A_TREND_UNANIM',                core4 + ['g_3a_trend_unanimity_with'], 'v8'),
    ('V8_PJ_3A_TREND_UNANIM_STRONG',         core4 + ['g_3a_trend_unanimity_strong_with'], 'v8'),
    # 2-asset RF confluence (BTC+SOL RF at ws_s-30s)
    ('V8_PJ_2A_RF_BTC_SOL',                  core4 + ['g_2a_rf_btc_sol_with'], 'v8'),
    # 3-asset RF unanimity + trend (replication of V7 g_pw_xa with TS)
    ('V8_PJ_3A_RF_AND_TREND',                core4 + ['g_3a_rf_and_trend_with'], 'v8'),
    ('V8_PJ_3A_RF_AND_BTC_SOL_TREND',        core4 + ['g_pw_xa_unanimity_with','g_2a_btc_sol_trend_with'], 'v8'),
    # Confluence + V7 winner stack (cascade across paths)
    ('V8_PJ_V7TOP_AND_SOL_TREND',            v7_top + ['g_pw_sol_15m_trend_with'], 'v8'),
    ('V8_PJ_V7TOP_AND_3A_TREND',             v7_top + ['g_3a_trend_unanimity_with'], 'v8'),
    ('V8_PJ_V7TOP_AND_2A_BTC_SOL',           v7_top + ['g_2a_btc_sol_trend_with'], 'v8'),
    ('V8_PJ_V7TOP_AND_SOL_STRONG',           v7_top + ['g_pw_sol_15m_trend_strong_with'], 'v8'),
]

# ============================================================
# PATH K — TOD specialization
# ============================================================
# Apply each TOD bucket on TOP of V7 winner + various variants
path_k = [
    # V7 top within each TOD bucket
    ('V8_PK_V7TOP_ASIA',                     v7_top + ['g_tod_asia'], 'v8'),
    ('V8_PK_V7TOP_EURO',                     v7_top + ['g_tod_european'], 'v8'),
    ('V8_PK_V7TOP_US_PM',                    v7_top + ['g_tod_us_pm'], 'v8'),
    ('V8_PK_V7TOP_US_EVE',                   v7_top + ['g_tod_us_eve'], 'v8'),
    # V6 core4 + TOD (simpler)
    ('V8_PK_CORE_ASIA',                      core4 + ['g_tod_asia'], 'v8'),
    ('V8_PK_CORE_EURO',                      core4 + ['g_tod_european'], 'v8'),
    ('V8_PK_CORE_US_PM',                     core4 + ['g_tod_us_pm'], 'v8'),
    ('V8_PK_CORE_US_EVE',                    core4 + ['g_tod_us_eve'], 'v8'),
    # PW trend slope V6 winner + TOD
    ('V8_PK_PW_TS_ASIA',                     core4 + ['g_pw_trend_slope_with','g_tod_asia'], 'v8'),
    ('V8_PK_PW_TS_EURO',                     core4 + ['g_pw_trend_slope_with','g_tod_european'], 'v8'),
    ('V8_PK_PW_TS_US_PM',                    core4 + ['g_pw_trend_slope_with','g_tod_us_pm'], 'v8'),
    ('V8_PK_PW_TS_US_EVE',                   core4 + ['g_pw_trend_slope_with','g_tod_us_eve'], 'v8'),
    # Asia OR European morning combined (split V7 winner by 2-TOD)
    ('V8_PK_V7TOP_ASIA_OR_EURO_dummy',       v7_top, 'v8'),  # placeholder: handled below
]

# ============================================================
# PATH L — 1h grandparent cascade
# ============================================================
path_l = [
    # 1h trend ALONE
    ('V8_PL_1H_TREND',                       core4 + ['g_gp_1h_trend_with'], 'v8'),
    ('V8_PL_1H_TREND_STRONG',                core4 + ['g_gp_1h_trend_strong_with'], 'v8'),
    ('V8_PL_1H_TREND_EXTREME',               core4 + ['g_gp_1h_trend_extreme_with'], 'v8'),
    # 1h ranging (anti-cascade)
    ('V8_PL_1H_RANGING',                     core4 + ['g_gp_1h_ranging'], 'v8'),
    # Cascade 1h + 15m parent + dailyvwap (auto from g_cascade_*)
    ('V8_PL_CASCADE_ALIGNED',                core4 + ['g_cascade_5m_15m_1h_aligned'], 'v8'),
    ('V8_PL_CASCADE_FULL_STRONG',            core4 + ['g_cascade_full_strong'], 'v8'),
    # V7 winner + 1h cascade
    ('V8_PL_V7TOP_AND_1H_TREND',             v7_top + ['g_gp_1h_trend_with'], 'v8'),
    ('V8_PL_V7TOP_AND_1H_STRONG',            v7_top + ['g_gp_1h_trend_strong_with'], 'v8'),
    ('V8_PL_V7TOP_AND_1H_EXTREME',           v7_top + ['g_gp_1h_trend_extreme_with'], 'v8'),
    ('V8_PL_V7TOP_AND_CASCADE_STRONG',       v7_top + ['g_cascade_full_strong'], 'v8'),
    ('V8_PL_V7TOP_AND_CASCADE_ALIGNED',      v7_top + ['g_cascade_5m_15m_1h_aligned'], 'v8'),
]

# ============================================================
# PATH J + K + L cross-pollination (deepest stacks)
# ============================================================
path_jkl = [
    ('V8_JKL_V7TOP_SOL_AND_1H',              v7_top + ['g_pw_sol_15m_trend_with','g_gp_1h_trend_with'], 'v8'),
    ('V8_JKL_V7TOP_3A_AND_1H',               v7_top + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with'], 'v8'),
    ('V8_JKL_V7TOP_3A_AND_1H_STRONG',        v7_top + ['g_3a_trend_unanimity_with','g_gp_1h_trend_strong_with'], 'v8'),
    ('V8_JKL_V7TOP_2A_BTC_SOL_AND_1H',       v7_top + ['g_2a_btc_sol_trend_with','g_gp_1h_trend_with'], 'v8'),
    # 4-gate compositions
    ('V8_JKL_BASE_3A_1H_TREND',              core4 + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with'], 'v8'),
    ('V8_JKL_BASE_BTC_SOL_1H',               core4 + ['g_2a_btc_sol_trend_with','g_gp_1h_trend_with'], 'v8'),
    # Add TOD on top of best multi-path stack
    ('V8_JKL_V7TOP_3A_1H_ASIA',              v7_top + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with','g_tod_asia'], 'v8'),
    ('V8_JKL_V7TOP_3A_1H_EURO',              v7_top + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with','g_tod_european'], 'v8'),
    ('V8_JKL_V7TOP_3A_1H_US_PM',             v7_top + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with','g_tod_us_pm'], 'v8'),
    ('V8_JKL_V7TOP_3A_1H_US_EVE',            v7_top + ['g_3a_trend_unanimity_with','g_gp_1h_trend_with','g_tod_us_eve'], 'v8'),
]

# Combine
all_stacks = path_j + path_k + path_l + path_jkl
# Dedup
seen = set(); unique_stacks = []
for name, gates, sp in all_stacks:
    if name == 'V8_PK_V7TOP_ASIA_OR_EURO_dummy': continue  # placeholder
    key = (tuple(sorted(gates)), sp)
    if key in seen: continue
    seen.add(key)
    unique_stacks.append((name, gates, sp))
log(f"Total unique stacks to test: {len(unique_stacks)}")

results = []
for name, stack, split_kind in unique_stacks:
    missing = [g for g in stack if g not in fires.columns]
    if missing:
        log(f"  [SKIP] {name}: missing {missing}")
        continue
    mask = fires[stack].all(axis=1) > 0
    if mask.sum() == 0:
        log(f"  [skip] {name}: no fires")
        continue
    split_fn = v8_split if split_kind == 'v8' else hur22_split
    m = gated_metrics(fires, mask, split_fn=split_fn)
    if m is None: continue
    sub = fires[mask].copy()
    _, _, lock_m = split_fn(sub)
    p = bootstrap_p(sub[lock_m])
    m['bootstrap_p_lockbox'] = p
    passes, fails = passes_v8(m)
    m['passes_v8'] = passes
    m['fails'] = ';'.join(fails)
    m['sleeve_id'] = name
    m['gate_stack'] = '&'.join(stack)
    m['split_kind'] = split_kind
    m['n_gates'] = len(stack)
    # Projections to 32.7d (V8 brief §0)
    days_lock = max(1, m['days_lock'])
    days_full = max(1, m['days_full'])
    m['proj_32d'] = m['dpt_lock_25'] * (m['n_lock'] / days_lock) * 32.66 if m['n_lock'] > 0 else 0
    m['proj_full'] = m['dpt_full_25'] * (m['n_full'] / days_full) * 32.66 if m['n_full'] > 0 else 0
    m['proj_honest'] = min(m['proj_32d'], m['proj_full'])
    results.append(m)
    flag = 'PASS' if passes else 'fail'
    log(f"  [{flag}] {name:<40} ({split_kind},{len(stack)}g): n_f={m['n_full']:>4}|n_l={m['n_lock']:>4}|WR_l={m['wr_lock']:.3f}|dpt_l=${m['dpt_lock_25']:>6.2f}|DD=${m['max_dd_25']:>5.0f}|LS={m['loss_streak']:>2}|p={p:.3f}|proj_h=${m['proj_honest']:>6.0f}")

df = pd.DataFrame(results).sort_values('proj_honest', ascending=False)
df.to_csv(f"{OUT}/all_candidates_v8.csv", index=False)
log(f"\nTotal stacks evaluated: {len(df)}")
log(f"Passing V8 bar: {df.passes_v8.sum()}")

df_pass = df[df.passes_v8].copy().sort_values('proj_honest', ascending=False)
df_pass.to_csv(f"{OUT}/passing_v8.csv", index=False)
log(f"WROTE passing_v8.csv ({len(df_pass)} passing)")

# Top 5
top5 = df_pass.head(5)
log("\n" + "="*60)
log("TOP 5 V8 CANDIDATES (by proj_honest)")
log("="*60)
for _, r in top5.iterrows():
    log(f"  {r.sleeve_id:<40} | proj_h=${r.proj_honest:>6.0f} | n_lock={int(r.n_lock):>3} | WR={r.wr_lock:.3f} | dpt=${r.dpt_lock_25:.2f} | p={r.bootstrap_p_lockbox:.3f}")

# Write top5 file with V8 brief §5 schema
keep_cols_top5 = ['sleeve_id','gate_stack','split_kind','n_gates',
                  'n_train','n_val','n_lock','n_full',
                  'wr_train','wr_val','wr_lock','wr_full',
                  'dpt_train_25','dpt_val_25','dpt_lock_25','dpt_full_25',
                  'max_dd_25','loss_streak','sharpe_daily','bootstrap_p_lockbox',
                  'proj_32d','proj_full','proj_honest']
# Rename to match brief
rename_map = {'dpt_train_25':'dpt_25_train','dpt_val_25':'dpt_25_val',
              'dpt_lock_25':'dpt_25_lockbox','dpt_full_25':'dpt_25_full',
              'wr_lock':'wr_lockbox','n_lock':'n_lockbox',
              'sharpe_daily':'sharpe'}
top5_out = top5[keep_cols_top5].rename(columns=rename_map)
top5_out.to_csv(f"{OUT}/top_5_candidates_v8.csv", index=False)
log(f"WROTE top_5_candidates_v8.csv")
log("DONE search")
