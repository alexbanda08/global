"""Expand SOL 15m sniper search: aggressive combinatorial + per-direction + offset-cross.

Findings from 02_sniper_search:
- 0 candidates pass full sniper bar
- Best candidates: per-offset bin (60-120s and 720-840s) have high WR but small n
- Greedy paths produce overly-loose gates (n_full > 500)
- Loss streaks tend to be 6-10 which fails sniper threshold of <=6

Strategy:
- Run combinatorial 2-of-N, 3-of-N, 4-of-N within each offset bin (instead of all-window)
- Try per-direction (UP only, DOWN only) within offset bins
- Try high-impact additive gates: tr_stack_full + at least 2 directional gates
- Be EXTRA strict: WR_lockbox >= 75%, loss_streak <= 6 (use 'sniper_aware' scoring)
"""
import os, time, itertools, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m"

log("loading fires")
df = pd.read_parquet(f"{OUT}/sol_15m_fires_v2fix_gates.parquet")
log(f"loaded {len(df):,} fires")

df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
TRAIN_START = pd.Timestamp('2026-04-28', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-05-16', tz='UTC')   # 18d
VAL_END     = pd.Timestamp('2026-05-22', tz='UTC')   # 6d
LOCK_END    = pd.Timestamp('2026-05-26', tz='UTC')   # 4d

def split_masks(d):
    return (
        (d['fire_date'] >= TRAIN_START) & (d['fire_date'] < TRAIN_END),
        (d['fire_date'] >= TRAIN_END)   & (d['fire_date'] < VAL_END),
        (d['fire_date'] >= VAL_END)     & (d['fire_date'] < LOCK_END),
    )

# pnl already at $25 notional
def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        m &= (col == 1)
    return m

def compute_metrics(d, gates):
    m = gate_passes(d, gates)
    sub = d[m].sort_values('fire_us').reset_index(drop=True)
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, sum=0.0, max_dd=0.0, loss_streak=0, sharpe=np.nan, n_days=0)
    pnl = sub['pnl_legacy_usd'].values
    wr = sub['won'].mean() * 100
    dpt = pnl.mean()
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = peak - cum
    max_dd = float(dd.max()) if len(dd) else 0.0
    losers = (pnl < 0).astype(int)
    max_run = cur_run = 0
    for v in losers:
        if v == 1:
            cur_run += 1
            if cur_run > max_run: max_run = cur_run
        else:
            cur_run = 0
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    daily = sub.groupby('date')['pnl_legacy_usd'].sum()
    n_days = len(daily)
    if len(daily) > 1 and daily.std() > 0:
        sharpe = (daily.mean() / daily.std()) * np.sqrt(252)
    else:
        sharpe = 0.0
    return dict(n=n, wr=wr, dpt=dpt, sum=float(pnl.sum()),
                max_dd=max_dd, loss_streak=max_run, sharpe=float(sharpe), n_days=n_days)

def bootstrap_p(d, gates, n_iter=1000, seed=42):
    m = gate_passes(d, gates)
    sub = d[m]
    n = len(sub)
    if n < 10: return np.nan
    pnl = sub['pnl_legacy_usd'].values
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n, n)
        means[i] = pnl[idx].mean()
    se = means.std()
    if se == 0: return 0.5
    obs = pnl.mean()
    from math import erf, sqrt
    z = obs / se
    p = 0.5 * (1 - erf(z / sqrt(2)))
    return max(float(p), 1e-4)

# Useful gates with cov >= 50% AND non-trivial ones rate
ALL_GATES = sorted([c for c in df.columns if c.startswith('g_')])
def is_useful(g, d):
    cov = d[g].notna().mean()
    if cov < 0.50: return False
    ones = (d[g]==1).sum()
    zeros = (d[g]==0).sum()
    if min(ones, zeros) < 100: return False
    return True
USEFUL = [g for g in ALL_GATES if is_useful(g, df)]
log(f"useful gates: {len(USEFUL)}")

# Top-tier "sniper anchors" (rarer, more selective)
TIER1 = [g for g in USEFUL if (df[g]==1).mean() <= 0.20]
log(f"tier1 (rare, ones <= 20%): {len(TIER1)}")
log(f"  tier1 list: {TIER1}")

results = []

# ==== APPROACH 1: Exhaustive 2-of-tier1 ====
log("=== APPROACH 1: Exhaustive 2-of-tier1 with optional 1 broader gate ===")
BROADER = [g for g in USEFUL if 0.20 < (df[g]==1).mean() <= 0.60]
log(f"broader (20-60%): {len(BROADER)}")

# 2-gate combos from tier1 + optional 3rd from broader
for combo in itertools.combinations(TIER1, 2):
    gates = list(combo)
    m_tr, m_va, m_lo = split_masks(df)
    mt_tr = compute_metrics(df[m_tr], gates)
    mt_va = compute_metrics(df[m_va], gates)
    mt_lo = compute_metrics(df[m_lo], gates)
    full  = compute_metrics(df, gates)
    if full['n'] < 25 or full['n'] > 600: continue
    bp_lo = bootstrap_p(df[m_lo], gates) if mt_lo['n'] >= 10 else np.nan
    bp_fu = bootstrap_p(df, gates)
    r = dict(
        sleeve_id=f"EXH2_{combo[0][2:8]}_{combo[1][2:8]}", anchor='offset_60s+',
        gate_stack='&'.join(gates), depth=2,
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
        sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
        loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
        sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
        n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
        bootstrap_p_lockbox=bp_lo, bootstrap_p_full=bp_fu,
    )
    results.append(r)

log(f"after EXH2: {len(results)} candidates")

# 3-gate combos: tier1 pair + broader
for pair in itertools.combinations(TIER1, 2):
    for g3 in BROADER:
        gates = list(pair) + [g3]
        m_tr, m_va, m_lo = split_masks(df)
        full = compute_metrics(df, gates)
        if full['n'] < 25 or full['n'] > 600: continue
        mt_tr = compute_metrics(df[m_tr], gates)
        mt_va = compute_metrics(df[m_va], gates)
        mt_lo = compute_metrics(df[m_lo], gates)
        bp_lo = bootstrap_p(df[m_lo], gates) if mt_lo['n'] >= 10 else np.nan
        bp_fu = bootstrap_p(df, gates)
        r = dict(
            sleeve_id=f"EXH3_{pair[0][2:6]}_{pair[1][2:6]}_{g3[2:6]}", anchor='offset_60s+',
            gate_stack='&'.join(gates), depth=3,
            n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
            wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
            dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
            sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
            max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
            loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
            sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
            n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
            bootstrap_p_lockbox=bp_lo, bootstrap_p_full=bp_fu,
        )
        results.append(r)
log(f"after EXH3: {len(results)} candidates")

# ==== APPROACH 2: Per-offset combinations ====
log("=== APPROACH 2: Per-offset exhaustive 2-of-USEFUL ===")
for off_bin in df.offset_bin.unique():
    d_bin = df[df.offset_bin == off_bin].copy()
    if len(d_bin) < 500: continue
    m_tr_b, m_va_b, m_lo_b = split_masks(d_bin)
    # 2-of-tier1 within bin
    for combo in itertools.combinations(TIER1, 2):
        gates = list(combo)
        full = compute_metrics(d_bin, gates)
        if full['n'] < 25 or full['n'] > 500: continue
        mt_tr = compute_metrics(d_bin[m_tr_b], gates)
        mt_va = compute_metrics(d_bin[m_va_b], gates)
        mt_lo = compute_metrics(d_bin[m_lo_b], gates)
        bp_lo = bootstrap_p(d_bin[m_lo_b], gates) if mt_lo['n'] >= 10 else np.nan
        bp_fu = bootstrap_p(d_bin, gates)
        r = dict(
            sleeve_id=f"OFF_{off_bin}_2T_{combo[0][2:6]}_{combo[1][2:6]}", anchor=f'offset_{off_bin}s',
            gate_stack='&'.join(gates), depth=2,
            n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
            wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
            dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
            sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
            max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
            loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
            sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
            n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
            bootstrap_p_lockbox=bp_lo, bootstrap_p_full=bp_fu,
        )
        results.append(r)
log(f"after APPROACH 2: {len(results)} candidates")

# ==== APPROACH 3: Per-direction ====
log("=== APPROACH 3: Per-direction sniper anchors ===")
for direction in ['UP', 'DOWN']:
    d_dir = df[df.direction == direction].copy()
    log(f"  direction {direction}: {len(d_dir)} fires")
    m_tr_d, m_va_d, m_lo_d = split_masks(d_dir)
    for combo in itertools.combinations(TIER1, 2):
        gates = list(combo)
        full = compute_metrics(d_dir, gates)
        if full['n'] < 25 or full['n'] > 500: continue
        mt_tr = compute_metrics(d_dir[m_tr_d], gates)
        mt_va = compute_metrics(d_dir[m_va_d], gates)
        mt_lo = compute_metrics(d_dir[m_lo_d], gates)
        bp_lo = bootstrap_p(d_dir[m_lo_d], gates) if mt_lo['n'] >= 10 else np.nan
        bp_fu = bootstrap_p(d_dir, gates)
        r = dict(
            sleeve_id=f"DIR{direction}_2T_{combo[0][2:6]}_{combo[1][2:6]}", anchor=f'dir_{direction}',
            gate_stack='&'.join(gates), depth=2,
            n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
            wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
            dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
            sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
            max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
            loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
            sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
            n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
            bootstrap_p_lockbox=bp_lo, bootstrap_p_full=bp_fu,
        )
        results.append(r)
log(f"after APPROACH 3: {len(results)} candidates")

# ==== APPROACH 4: Late window + lots of gates ====
log("=== APPROACH 4: Late-window (480+s) restricted sniper ===")
d_late = df[df.fire_offset_s >= 480].copy()
log(f"  late-window fires: {len(d_late)}")
m_tr_l, m_va_l, m_lo_l = split_masks(d_late)
# 3-of-tier1 in late window
for combo in itertools.combinations(TIER1, 3):
    gates = list(combo)
    full = compute_metrics(d_late, gates)
    if full['n'] < 25 or full['n'] > 500: continue
    mt_tr = compute_metrics(d_late[m_tr_l], gates)
    mt_va = compute_metrics(d_late[m_va_l], gates)
    mt_lo = compute_metrics(d_late[m_lo_l], gates)
    bp_lo = bootstrap_p(d_late[m_lo_l], gates) if mt_lo['n'] >= 10 else np.nan
    bp_fu = bootstrap_p(d_late, gates)
    r = dict(
        sleeve_id=f"LATE_3T_{combo[0][2:6]}_{combo[1][2:6]}_{combo[2][2:6]}", anchor='late_480s+',
        gate_stack='&'.join(gates), depth=3,
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
        sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
        loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
        sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
        n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
        bootstrap_p_lockbox=bp_lo, bootstrap_p_full=bp_fu,
    )
    results.append(r)
log(f"after APPROACH 4: {len(results)} candidates")

# Save and rank
res_df = pd.DataFrame(results)
res_df.to_csv(f"{OUT}/all_candidates_v3_expanded.csv", index=False)
log(f"WROTE all_candidates_v3_expanded.csv ({len(res_df)} rows)")

# Sniper filter
def passes_sniper(r):
    if r['n_lockbox'] < 5: return False
    if r['n_full'] > 500: return False
    n_per_32d = r['n_full'] * (32.0/28.0)
    if n_per_32d < 50: return False
    if r['wr_lockbox'] < 75: return False
    if r['dpt_25'] < 3: return False
    if r['max_dd_25'] > 300: return False
    if r['loss_streak'] > 6: return False
    if r['sharpe'] < 2: return False
    if pd.isna(r['bootstrap_p_lockbox']) or r['bootstrap_p_lockbox'] > 0.05: return False
    return True

# Sniper-aware scoring
def sniper_score(r):
    s = 0
    if r['wr_lockbox'] >= 75: s += 1
    if r['dpt_25'] >= 3: s += 1
    if r['max_dd_25'] <= 300: s += 1
    if r['loss_streak'] <= 6: s += 1
    if r['sharpe'] >= 2: s += 1
    if r['n_lockbox'] >= 5 and r['n_full'] <= 500: s += 1
    if pd.notna(r['bootstrap_p_lockbox']) and r['bootstrap_p_lockbox'] <= 0.05: s += 1
    return s

res_df['pass_sniper'] = res_df.apply(passes_sniper, axis=1)
res_df['sniper_score'] = res_df.apply(sniper_score, axis=1)

sniper = res_df[res_df.pass_sniper].sort_values('dpt_25', ascending=False)
log(f"FULL-PASS sniper candidates: {len(sniper)}")
for _, r in sniper.head(20).iterrows():
    log(f"  PASS {r['sleeve_id']:50} lock n={r['n_lockbox']:3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f} dd=${r['max_dd_25']:.0f} sr={r['sharpe']:.2f}")

# Top by sniper_score among 6+/7
near = res_df[(res_df.sniper_score >= 5) & (res_df.n_lockbox >= 5)].sort_values(['sniper_score','dpt_25'], ascending=[False,False])
log(f"6+/7 sniper score: {len(res_df[res_df.sniper_score>=6])}")
log(f"5+/7 sniper score (with lock n>=5): {len(near)}")
log(f"\n=== Top 15 by score then dpt ===")
for _, r in near.head(15).iterrows():
    log(f"  S={r['sniper_score']} {r['sleeve_id']:50} lock n={r['n_lockbox']:3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f} dd=${r['max_dd_25']:.0f} streak={r['loss_streak']} sr={r['sharpe']:.2f} p={r['bootstrap_p_lockbox']:.3f}")

# Top 5
if len(sniper):
    top5 = sniper.head(5)
else:
    top5 = near.head(5)
top5.to_csv(f"{OUT}/top_5_candidates.csv", index=False)
log(f"WROTE top_5_candidates.csv ({len(top5)})")
log("DONE")
