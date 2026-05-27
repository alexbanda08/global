"""V6 ETH 15m — Kelly sizing, simulated PnL, final top-5 selection.

Builds:
  1. top_5_candidates_v6.csv (final picks ranked by v6_score = dpt_lock × sqrt(n_lock))
  2. kelly_stake_table_<sleeve_id>.csv per top sleeve — conviction-bucket Kelly schedule
  3. cumulative_pnl_kelly_vs_const_<sleeve_id>.png per top sleeve
  4. SNIPER_ETH_15M_V6_REPORT.md

Conviction method: Option B (empirical WR per bucket of # extra gates passing).
Base stack = the candidate's "core" gates (minimum to qualify). Extra gates added
beyond core build conviction.

For each top sleeve we:
  - Define core_stack (size <= 3-4 most-essential gates from the stack)
  - Compute extra_gates = stack - core_stack
  - For each train fire passing core_stack, count # of extra_gates also passing
    → conviction bucket = count
  - Compute empirical_WR per bucket on train+val (out-of-sample for lock)
  - For lockbox fires: assign bucket via gate-count, then stake = Kelly(p_bucket, vwap)

Kelly:
  b = (1 - vwap) * 0.98 / vwap
  f_full = (p*b - (1-p)) / b
  f_kelly_25 = max(0, 0.25 * f_full)
  stake = clip(f_kelly_25 * STAKE_MAX, STAKE_MIN, STAKE_MAX)
"""
import os, time, warnings, json
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v6"

# =========================================================
# 1. Load enriched + candidate list
# =========================================================
log("loading enriched")
fires = pd.read_parquet(f"{OUT}/eth_15m_enriched_v6.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date

log("loading all_candidates_v6")
allc = pd.read_csv(f"{OUT}/all_candidates_v6.csv")
log(f"  rows: {len(allc)} | passing: {allc.passes_v6.sum()}")

# v6_score
allc['v6_score'] = allc.dpt_lock_25 * np.sqrt(np.maximum(0, allc.n_lock))

# =========================================================
# 2. Cohort split (same as search)
# =========================================================
def cohort_split(df, cohort):
    if cohort == 'FULL':
        train = df.date < pd.to_datetime('2026-05-15').date()
        val   = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-22').date())
        lock  = df.date >= pd.to_datetime('2026-05-22').date()
    elif cohort == 'MP31':
        train = df.date < pd.to_datetime('2026-05-15').date()
        val   = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-21').date())
        lock  = (df.date >= pd.to_datetime('2026-05-21').date()) & (df.date <= pd.to_datetime('2026-05-25').date())
    elif cohort == 'REG28':
        train = (df.date >= pd.to_datetime('2026-04-28').date()) & (df.date < pd.to_datetime('2026-05-14').date())
        val   = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-20').date())
        lock  = (df.date >= pd.to_datetime('2026-05-20').date()) & (df.date <= pd.to_datetime('2026-05-25').date())
    elif cohort == 'HUR22':
        train = (df.date >= pd.to_datetime('2026-05-01').date()) & (df.date < pd.to_datetime('2026-05-14').date())
        val   = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-18').date())
        lock  = (df.date >= pd.to_datetime('2026-05-18').date()) & (df.date <= pd.to_datetime('2026-05-22').date())
    return train, val, lock

# =========================================================
# 3. Pick top 5 diverse candidates from passing list
# =========================================================
passing = allc[allc.passes_v6 == True].copy().sort_values('v6_score', ascending=False)
log(f"passing sleeves: {len(passing)}")
log("Top 10 passing by v6_score:")
for _, r in passing.head(10).iterrows():
    log(f"  {r.sleeve_id:<35} | cohort={r.cohort:<6} | n_lk={int(r.n_lock):3d} | WR={r.wr_lock:.3f} | dpt=${r.dpt_lock_25:.2f} | DD=${r.max_dd_25:.0f} | LS={int(r.loss_streak):2d} | score={r.v6_score:.1f}")

# Picking strategy: top by score with curated diversity.
# Pick #1: best by v6_score (S1 family)
# Pick #2: best of S1-PW family (pre-window swap-in) — different anchor concept
# Pick #3: directional asymmetric (DOWN-only) if positive
# Pick #4: broader cohort (MP31/REG28) for slug coverage
# Pick #5: best non-HUR22 sleeve for safety / panel-light deploy
def stack_set(s):
    return frozenset(s.split('&'))

picks = []
picked_keys = set()
# Tier 1: best overall
def add_pick(sid_target):
    rows = passing[passing.sleeve_id == sid_target]
    if rows.empty: return False
    r = rows.iloc[0]
    sset = stack_set(r.gate_stack)
    if sset in picked_keys: return False
    picked_keys.add(sset)
    picks.append({
        'sleeve_id': r.sleeve_id, 'gate_stack': r.gate_stack, 'cohort': r.cohort,
        'n_full': int(r.n_full), 'n_lock': int(r.n_lock),
        'wr_lock': r.wr_lock, 'dpt_lock_25': r.dpt_lock_25,
        'max_dd_25': r.max_dd_25, 'loss_streak': int(r.loss_streak),
        'bootstrap_p': r.bootstrap_p, 'v6_score': r.v6_score,
        'sharpe_daily': r.sharpe_daily, 'fires_per_day': r.fires_per_day,
        'wr_train': r.wr_train, 'wr_val': r.wr_val,
        'n_train': int(r.n_train), 'n_val': int(r.n_val),
        'dpt_train_25': r.dpt_train_25, 'dpt_val_25': r.dpt_val_25,
        'sum_pnl_full': r.sum_pnl_full, 'sum_pnl_lock': r.sum_pnl_lock,
        'days_lock': int(r.days_lock),
        'boot_ci_lo_$25': r['boot_ci_lo_$25'], 'boot_ci_hi_$25': r['boot_ci_hi_$25'],
    })
    return True

# Curated top-5 for V6 deployment diversity:
add_pick('V6_S1_VWAP_3070')       # best base S1 family, +VWAP band
add_pick('V6_S1_PW_TREND_SLOPE')  # pre-window anchor, different signal
add_pick('V6_S1_DOWN_ONLY')       # directional asymmetric (DOWN-only)
add_pick('V6_S5_PW_TREND_SLOPE')  # broader cohort MP31, panel-light
add_pick('V5_S3_REPL')            # FULL cohort fallback (panel-independent)

# Fallback fill (if curated pick was missing from passing list)
if len(picks) < 5:
    for _, r in passing.iterrows():
        if len(picks) >= 5: break
        sset = stack_set(r.gate_stack)
        if sset in picked_keys: continue
        picked_keys.add(sset)
        picks.append({
            'sleeve_id': r.sleeve_id, 'gate_stack': r.gate_stack, 'cohort': r.cohort,
            'n_full': int(r.n_full), 'n_lock': int(r.n_lock),
            'wr_lock': r.wr_lock, 'dpt_lock_25': r.dpt_lock_25,
            'max_dd_25': r.max_dd_25, 'loss_streak': int(r.loss_streak),
            'bootstrap_p': r.bootstrap_p, 'v6_score': r.v6_score,
            'sharpe_daily': r.sharpe_daily, 'fires_per_day': r.fires_per_day,
            'wr_train': r.wr_train, 'wr_val': r.wr_val,
            'n_train': int(r.n_train), 'n_val': int(r.n_val),
            'dpt_train_25': r.dpt_train_25, 'dpt_val_25': r.dpt_val_25,
            'sum_pnl_full': r.sum_pnl_full, 'sum_pnl_lock': r.sum_pnl_lock,
            'days_lock': int(r.days_lock),
            'boot_ci_lo_$25': r['boot_ci_lo_$25'], 'boot_ci_hi_$25': r['boot_ci_hi_$25'],
        })

log(f"\nPicked top {len(picks)} diverse sleeves:")
for p in picks:
    log(f"  {p['sleeve_id']} ({p['cohort']}) -- n_lock={p['n_lock']}, score={p['v6_score']:.1f}")

# =========================================================
# 4. Kelly stake computation per sleeve
# =========================================================

STAKE_MIN = 5.0
STAKE_MAX = 25.0

def kelly_stake(p, vwap, fraction=0.25):
    """Fractional-Kelly stake within [STAKE_MIN, STAKE_MAX]."""
    if vwap <= 0 or vwap >= 1: return STAKE_MIN
    b = (1.0 - vwap) * 0.98 / vwap   # profit per dollar if won
    f_full = (p * b - (1.0 - p)) / b
    f_kelly = max(0.0, fraction * f_full)
    stake = min(STAKE_MAX, max(STAKE_MIN, f_kelly * STAKE_MAX))
    return stake

def linear_conviction_stake(bucket_idx, max_bucket):
    """Per-bucket linear stake in [STAKE_MIN, STAKE_MAX] (Option A: gate-count)."""
    if max_bucket <= 0:
        return STAKE_MAX
    conviction = bucket_idx / max_bucket
    return STAKE_MIN + (STAKE_MAX - STAKE_MIN) * conviction

def hybrid_stake(p, vwap, bucket_idx, max_bucket):
    """V6 deployable stake = MAX of:
       (a) 0.5x Kelly (somewhat aggressive but conservative vs full Kelly)
       (b) Linear conviction stake from gate-count (Option A)
       Capped to [STAKE_MIN, STAKE_MAX].
    """
    k = kelly_stake(p, vwap, fraction=0.5)  # half-Kelly (less conservative than quarter)
    l = linear_conviction_stake(bucket_idx, max_bucket)
    return max(STAKE_MIN, min(STAKE_MAX, max(k, l)))

# For each sleeve:
#   - Define core_stack: the gates always required (we use cohort-typical 3 gates for ETH 15m)
#     For S1 family: core = [g_tr_stack_full_with, g_above_1h_dailyvwap_with, g_offset_early]
#                    (these are the V5 winning anchor — vol_high + others build conviction)
#   - extra_gates = full_stack - core_stack
def parse_stack(s):
    return s.split('&')

# Pick core for each pick
def pick_core(stack_list):
    """Heuristic: core = anchors that appear in most top sleeves.
    For ETH 15m, the universal anchors are g_offset_early + g_above_1h_dailyvwap_with."""
    universal = ['g_offset_early', 'g_above_1h_dailyvwap_with']
    core = [g for g in universal if g in stack_list]
    # If stack has g_tr_stack_full_with, add it (it's the V5 cornerstone)
    if 'g_tr_stack_full_with' in stack_list and len(core) < 3:
        core.append('g_tr_stack_full_with')
    return core

def kelly_table(fires, stack, cohort, sleeve_id):
    """Build conviction-bucket Kelly schedule + simulate Kelly vs constant-25 PnL."""
    core = pick_core(stack)
    extras = [g for g in stack if g not in core]
    log(f"  [{sleeve_id}] core={core} | extras={extras}")

    # Compute mask passing core only (this is the broader funnel)
    core_mask = fires[core].all(axis=1) > 0 if core else np.ones(len(fires), dtype=bool)
    if isinstance(core_mask, pd.Series): core_mask = core_mask.values
    sub_core = fires[core_mask].copy()
    if len(sub_core) == 0:
        log(f"    no core fires")
        return None

    # For each core-passing fire, count # extras passing -> conviction bucket
    if extras:
        bucket = sub_core[extras].sum(axis=1).astype(int).values
    else:
        bucket = np.zeros(len(sub_core), dtype=int)
    sub_core['conviction_bucket'] = bucket

    # Cohort split on core-passing
    train_m, val_m, lock_m = cohort_split(sub_core, cohort)

    # Compute empirical_WR per bucket on TRAIN+VAL (out-of-sample for lockbox)
    train_val = sub_core[train_m | val_m]
    max_bucket = len(extras)
    bucket_stats = []
    for b_val in range(max_bucket + 1):
        b_sub = train_val[train_val.conviction_bucket == b_val]
        n_tv = len(b_sub)
        wr_tv = b_sub.won.mean() if n_tv > 0 else 0.5
        # vwap stats
        vwap_med = b_sub.entry_vwap.median() if n_tv > 0 else 0.5
        # Stake calculations: quarter-Kelly (conservative), half-Kelly, linear, hybrid
        stake_q_kelly  = kelly_stake(wr_tv, vwap_med, fraction=0.25) if vwap_med > 0 and vwap_med < 1 else STAKE_MIN
        stake_h_kelly  = kelly_stake(wr_tv, vwap_med, fraction=0.5)  if vwap_med > 0 and vwap_med < 1 else STAKE_MIN
        stake_linear   = linear_conviction_stake(b_val, max_bucket)
        stake_hybrid   = hybrid_stake(wr_tv, vwap_med, b_val, max_bucket)
        bucket_stats.append({
            'conviction_bucket': b_val,
            'n_train_val': int(n_tv),
            'empirical_wr_train_val': float(wr_tv),
            'median_vwap': float(vwap_med),
            'stake_quarter_kelly': float(stake_q_kelly),
            'stake_half_kelly': float(stake_h_kelly),
            'stake_linear_conviction': float(stake_linear),
            'stake_hybrid_deploy': float(stake_hybrid),
            'lookalike_b': float((1.0 - vwap_med) * 0.98 / vwap_med) if vwap_med > 0 and vwap_med < 1 else 0.0,
        })

    # Apply per-bucket stake to lockbox fires (and full window for simulation)
    bucket_wr_map = {b['conviction_bucket']: b['empirical_wr_train_val'] for b in bucket_stats}

    # For full sleeve evaluation, the sleeve is "fires passing ALL stack gates"
    full_mask = fires[stack].all(axis=1) > 0
    if isinstance(full_mask, pd.Series): full_mask = full_mask.values
    sleeve_fires = fires[full_mask].copy()
    sleeve_fires = sleeve_fires.sort_values('fire_us').reset_index(drop=True)
    # All sleeve fires necessarily pass core too. Compute their bucket:
    if extras:
        sleeve_fires['conviction_bucket'] = sleeve_fires[extras].sum(axis=1).astype(int).values
    else:
        sleeve_fires['conviction_bucket'] = 0

    # For Kelly stake we use bucket-empirical WR (or fall back to overall WR for unseen buckets)
    overall_wr = train_val.won.mean() if len(train_val) > 0 else 0.5
    def get_p(b):
        return bucket_wr_map.get(int(b), overall_wr)

    # The sleeve uses ALL extra gates (i.e. max conviction). So bucket == len(extras).
    # But Kelly cells from bucket_stats tell us "what would the stake be if we relaxed"
    # For ACTUAL deploy we report what the sleeve fires use (max bucket).
    sleeve_fires['p_kelly'] = sleeve_fires.conviction_bucket.apply(get_p)
    sleeve_fires['stake_quarter_kelly'] = [
        kelly_stake(p, v, fraction=0.25) for p, v in zip(sleeve_fires.p_kelly, sleeve_fires.entry_vwap)
    ]
    sleeve_fires['stake_half_kelly'] = [
        kelly_stake(p, v, fraction=0.5) for p, v in zip(sleeve_fires.p_kelly, sleeve_fires.entry_vwap)
    ]
    max_b = max(1, len(extras))
    sleeve_fires['stake_linear'] = [
        linear_conviction_stake(int(b), max_b) for b in sleeve_fires.conviction_bucket
    ]
    sleeve_fires['stake_hybrid'] = [
        hybrid_stake(p, v, int(b), max_b)
        for p, v, b in zip(sleeve_fires.p_kelly, sleeve_fires.entry_vwap, sleeve_fires.conviction_bucket)
    ]
    # PnL scaled: pnl_legacy_usd is at $25 stake. Scale by chosen variable stake.
    sleeve_fires['pnl_quarter_kelly'] = sleeve_fires.pnl_legacy_usd * (sleeve_fires.stake_quarter_kelly / 25.0)
    sleeve_fires['pnl_half_kelly']    = sleeve_fires.pnl_legacy_usd * (sleeve_fires.stake_half_kelly / 25.0)
    sleeve_fires['pnl_linear']        = sleeve_fires.pnl_legacy_usd * (sleeve_fires.stake_linear / 25.0)
    sleeve_fires['pnl_hybrid']        = sleeve_fires.pnl_legacy_usd * (sleeve_fires.stake_hybrid / 25.0)
    sleeve_fires['pnl_const_25']      = sleeve_fires.pnl_legacy_usd

    # === Simulate lockbox PnL: Hybrid vs const $25 (and other modes)
    train_m2, val_m2, lock_m2 = cohort_split(sleeve_fires, cohort)
    sleeve_lock = sleeve_fires[lock_m2].sort_values('fire_us').reset_index(drop=True)

    sum_quarter_kelly_lock = sleeve_lock.pnl_quarter_kelly.sum()
    sum_half_kelly_lock    = sleeve_lock.pnl_half_kelly.sum()
    sum_linear_lock        = sleeve_lock.pnl_linear.sum()
    sum_hybrid_lock        = sleeve_lock.pnl_hybrid.sum()
    sum_const_lock = sleeve_lock.pnl_const_25.sum()
    n_lock = len(sleeve_lock)

    # Full-window sim sums
    sum_quarter_kelly_full = sleeve_fires.pnl_quarter_kelly.sum()
    sum_half_kelly_full    = sleeve_fires.pnl_half_kelly.sum()
    sum_linear_full        = sleeve_fires.pnl_linear.sum()
    sum_hybrid_full        = sleeve_fires.pnl_hybrid.sum()
    sum_const_full = sleeve_fires.pnl_const_25.sum()
    n_full = len(sleeve_fires)

    sum_kelly_lock = sum_quarter_kelly_lock  # back-compat alias
    sum_kelly_full = sum_quarter_kelly_full

    # === ALSO: simulate CORE-stack universe with variable stake (the real Kelly uplift demo)
    # This is the "what if we used the WIDER core funnel but sized smaller for low-conviction fires"
    core_fires = sub_core.sort_values('fire_us').reset_index(drop=True).copy()
    core_fires['p_kelly'] = core_fires.conviction_bucket.apply(get_p)
    core_fires['stake_hybrid'] = [
        hybrid_stake(p, v, int(b), max_b)
        for p, v, b in zip(core_fires.p_kelly, core_fires.entry_vwap, core_fires.conviction_bucket)
    ]
    core_fires['stake_quarter_kelly'] = [
        kelly_stake(p, v, fraction=0.25) for p, v in zip(core_fires.p_kelly, core_fires.entry_vwap)
    ]
    core_fires['stake_linear'] = [
        linear_conviction_stake(int(b), max_b) for b in core_fires.conviction_bucket
    ]
    core_fires['pnl_hybrid_core']        = core_fires.pnl_legacy_usd * (core_fires.stake_hybrid / 25.0)
    core_fires['pnl_quarter_kelly_core'] = core_fires.pnl_legacy_usd * (core_fires.stake_quarter_kelly / 25.0)
    core_fires['pnl_linear_core']        = core_fires.pnl_legacy_usd * (core_fires.stake_linear / 25.0)
    core_fires['pnl_const_25_core']      = core_fires.pnl_legacy_usd  # core fires at const $25

    tm_c, vm_c, lm_c = cohort_split(core_fires, cohort)
    core_lock = core_fires[lm_c]
    sum_core_const_lock         = core_lock.pnl_const_25_core.sum()
    sum_core_hybrid_lock        = core_lock.pnl_hybrid_core.sum()
    sum_core_quarter_kelly_lock = core_lock.pnl_quarter_kelly_core.sum()
    sum_core_linear_lock        = core_lock.pnl_linear_core.sum()
    sum_core_const_full         = core_fires.pnl_const_25_core.sum()
    sum_core_hybrid_full        = core_fires.pnl_hybrid_core.sum()
    sum_core_quarter_kelly_full = core_fires.pnl_quarter_kelly_core.sum()
    sum_core_linear_full        = core_fires.pnl_linear_core.sum()
    n_core_lock = len(core_lock); n_core_full = len(core_fires)

    return {
        'core': core, 'extras': extras,
        'bucket_stats': bucket_stats,
        'sleeve_fires': sleeve_fires,
        'sleeve_lock': sleeve_lock,
        'sum_kelly_lock': sum_kelly_lock,
        'sum_const_lock': sum_const_lock,
        'sum_kelly_full': sum_kelly_full,
        'sum_const_full': sum_const_full,
        'sum_quarter_kelly_lock': sum_quarter_kelly_lock,
        'sum_half_kelly_lock': sum_half_kelly_lock,
        'sum_linear_lock': sum_linear_lock,
        'sum_hybrid_lock': sum_hybrid_lock,
        'sum_quarter_kelly_full': sum_quarter_kelly_full,
        'sum_half_kelly_full': sum_half_kelly_full,
        'sum_linear_full': sum_linear_full,
        'sum_hybrid_full': sum_hybrid_full,
        'n_lock': n_lock, 'n_full': n_full,
        'bucket_wr_map': bucket_wr_map,
        # Core (broader funnel) simulations
        'core_fires': core_fires,
        'sum_core_const_lock': sum_core_const_lock,
        'sum_core_hybrid_lock': sum_core_hybrid_lock,
        'sum_core_quarter_kelly_lock': sum_core_quarter_kelly_lock,
        'sum_core_linear_lock': sum_core_linear_lock,
        'sum_core_const_full': sum_core_const_full,
        'sum_core_hybrid_full': sum_core_hybrid_full,
        'sum_core_quarter_kelly_full': sum_core_quarter_kelly_full,
        'sum_core_linear_full': sum_core_linear_full,
        'n_core_lock': n_core_lock, 'n_core_full': n_core_full,
    }

# =========================================================
# 5. Process each pick
# =========================================================
kelly_results = {}
for p in picks:
    sid = p['sleeve_id']; stack = parse_stack(p['gate_stack']); cohort = p['cohort']
    log(f"\n=== {sid} ({cohort}) ===")
    res = kelly_table(fires, stack, cohort, sid)
    if res is None:
        log(f"  SKIP — no fires after core")
        continue
    kelly_results[sid] = res

    # Write bucket table CSV
    bdf = pd.DataFrame(res['bucket_stats'])
    bdf['sleeve_id'] = sid
    bdf['core_gates'] = ' & '.join(res['core'])
    bdf['extra_gates'] = ' & '.join(res['extras'])
    bdf.to_csv(f"{OUT}/kelly_stake_table_{sid}.csv", index=False)

    # Console summary
    log(f"  conviction buckets ({len(res['extras'])} extras):")
    for b in res['bucket_stats']:
        log(f"    bucket={b['conviction_bucket']} | n_tv={b['n_train_val']:>4} | WR={b['empirical_wr_train_val']:.3f} | vwap={b['median_vwap']:.3f} | qK=${b['stake_quarter_kelly']:.2f} hK=${b['stake_half_kelly']:.2f} lin=${b['stake_linear_conviction']:.2f} hyb=${b['stake_hybrid_deploy']:.2f}")
    log(f"  lockbox PnL: const_$25=${res['sum_const_lock']:.0f} | qK=${res['sum_quarter_kelly_lock']:.0f} | hK=${res['sum_half_kelly_lock']:.0f} | lin=${res['sum_linear_lock']:.0f} | hyb=${res['sum_hybrid_lock']:.0f}")
    log(f"  full     PnL: const_$25=${res['sum_const_full']:.0f} | qK=${res['sum_quarter_kelly_full']:.0f} | hK=${res['sum_half_kelly_full']:.0f} | lin=${res['sum_linear_full']:.0f} | hyb=${res['sum_hybrid_full']:.0f}")

# =========================================================
# 6. Plot cumulative Kelly vs const $25 per sleeve (full window)
# =========================================================
log("\nPlotting cumulative PnL: Kelly vs const $25...")
for sid, res in kelly_results.items():
    sf = res['sleeve_fires'].sort_values('fire_us').reset_index(drop=True)
    sf['dt'] = pd.to_datetime(sf.fire_us, unit='us', utc=True)
    sf['cum_const_25']     = sf.pnl_const_25.cumsum()
    sf['cum_quarter_kelly']= sf.pnl_quarter_kelly.cumsum()
    sf['cum_half_kelly']   = sf.pnl_half_kelly.cumsum()
    sf['cum_linear']       = sf.pnl_linear.cumsum()
    sf['cum_hybrid']       = sf.pnl_hybrid.cumsum()
    # Core variant (broader funnel)
    cf = res['core_fires'].sort_values('fire_us').reset_index(drop=True)
    cf['dt'] = pd.to_datetime(cf.fire_us, unit='us', utc=True)
    cf['cum_core_const']  = cf.pnl_const_25_core.cumsum()
    cf['cum_core_hybrid'] = cf.pnl_hybrid_core.cumsum()
    cf['cum_core_qk']     = cf.pnl_quarter_kelly_core.cumsum()
    cf['cum_core_linear'] = cf.pnl_linear_core.cumsum()

    fig, axes = plt.subplots(2, 1, figsize=(13, 10))
    # Top: full-stack sleeve (the actual deployment unit)
    ax = axes[0]
    ax.plot(sf.dt, sf.cum_const_25,      label=f"Const $25 (n={len(sf)}, final ${sf.cum_const_25.iloc[-1]:.0f})", color='C0', alpha=0.9, linewidth=2)
    ax.plot(sf.dt, sf.cum_quarter_kelly, label=f"Quarter-Kelly (final ${sf.cum_quarter_kelly.iloc[-1]:.0f})", color='C1', alpha=0.75, linestyle='--')
    ax.plot(sf.dt, sf.cum_half_kelly,    label=f"Half-Kelly (final ${sf.cum_half_kelly.iloc[-1]:.0f})", color='C2', alpha=0.85)
    ax.plot(sf.dt, sf.cum_hybrid,        label=f"Hybrid max(½K, linear) (final ${sf.cum_hybrid.iloc[-1]:.0f})", color='C4', alpha=0.95, linewidth=2.5)
    cohort_this = picks[[p['sleeve_id'] for p in picks].index(sid)]['cohort']
    train_m, val_m, lock_m = cohort_split(sf, cohort_this)
    if lock_m.sum() > 0:
        ax.axvline(sf[lock_m].dt.min(), color='gray', linestyle='--', alpha=0.5, label=f'Lockbox start')
    ax.set_title(f"V6 ETH 15m — {sid} — FULL STACK fires (deploy unit)\nGates: {' & '.join(parse_stack([p['gate_stack'] for p in picks if p['sleeve_id']==sid][0]))}", fontsize=10)
    ax.set_ylabel("Cumulative PnL ($)")
    ax.grid(alpha=0.3); ax.legend(loc='upper left', fontsize=8)

    # Bottom: CORE-stack funnel (broader, illustrates conviction sizing uplift)
    ax = axes[1]
    ax.plot(cf.dt, cf.cum_core_const,  label=f"Core+const $25 (n={len(cf)}, final ${cf.cum_core_const.iloc[-1]:.0f})", color='C5', alpha=0.85, linestyle='--')
    ax.plot(cf.dt, cf.cum_core_qk,     label=f"Core+quarter-Kelly (final ${cf.cum_core_qk.iloc[-1]:.0f})", color='C1', alpha=0.7, linestyle=':')
    ax.plot(cf.dt, cf.cum_core_linear, label=f"Core+linear conviction (final ${cf.cum_core_linear.iloc[-1]:.0f})", color='C3', alpha=0.85)
    ax.plot(cf.dt, cf.cum_core_hybrid, label=f"Core+hybrid (final ${cf.cum_core_hybrid.iloc[-1]:.0f})", color='C4', alpha=0.95, linewidth=2.5)
    # Overlay full-stack hybrid for comparison
    ax.plot(sf.dt, sf.cum_hybrid, label=f"Full-stack hybrid (n={len(sf)}, final ${sf.cum_hybrid.iloc[-1]:.0f})", color='C0', alpha=0.9, linewidth=2)
    train_m_c, val_m_c, lock_m_c = cohort_split(cf, cohort_this)
    if lock_m_c.sum() > 0:
        ax.axvline(cf[lock_m_c].dt.min(), color='gray', linestyle='--', alpha=0.5, label='Lockbox start')
    ax.set_title(f"CORE-stack funnel ({' & '.join(res['core'])}) — conviction sizing uplift", fontsize=10)
    ax.set_xlabel("Date"); ax.set_ylabel("Cumulative PnL ($)")
    ax.grid(alpha=0.3); ax.legend(loc='upper left', fontsize=8)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(f"{OUT}/cumulative_pnl_kelly_vs_const_{sid}.png", dpi=110, bbox_inches='tight')
    plt.close(fig)
    log(f"  WROTE cumulative_pnl_kelly_vs_const_{sid}.png")

# =========================================================
# 7. Top-5 final CSV
# =========================================================
log("\nBuilding top_5_candidates_v6.csv")
top5_rows = []
for p in picks:
    sid = p['sleeve_id']
    res = kelly_results.get(sid)
    if res is None:
        sum_qk = sum_hk = sum_lin = sum_hyb = sum_qk_full = sum_hyb_full = 0.0
    else:
        sum_qk     = res['sum_quarter_kelly_lock']
        sum_hk     = res['sum_half_kelly_lock']
        sum_lin    = res['sum_linear_lock']
        sum_hyb    = res['sum_hybrid_lock']
        sum_qk_full = res['sum_quarter_kelly_full']
        sum_hyb_full = res['sum_hybrid_full']
    row = {
        'sleeve_id': sid,
        'anchor': 'offset_early (60s) + ws_s gates' if 'pw' in p['gate_stack'] else 'offset_early (60s)',
        'gate_stack': p['gate_stack'],
        'cohort': p['cohort'],
        'n_train': p['n_train'], 'n_val': p['n_val'], 'n_lockbox': p['n_lock'],
        'wr_train': round(p['wr_train'], 4),
        'wr_val': round(p['wr_val'], 4),
        'wr_lockbox': round(p['wr_lock'], 4),
        'dpt_25_lockbox': round(p['dpt_lock_25'], 2),
        'sum_25_const_lockbox': round(p['sum_pnl_lock'], 2),
        'sum_25_quarter_kelly_lockbox': round(sum_qk, 2),
        'sum_25_half_kelly_lockbox':   round(sum_hk, 2),
        'sum_25_linear_lockbox':       round(sum_lin, 2),
        'sum_25_hybrid_lockbox':       round(sum_hyb, 2),
        'sum_25_const_full':       round(p['sum_pnl_full'], 2),
        'sum_25_quarter_kelly_full': round(sum_qk_full, 2),
        'sum_25_hybrid_full':        round(sum_hyb_full, 2),
        'max_dd_25': round(p['max_dd_25'], 2),
        'loss_streak': p['loss_streak'],
        'sharpe_daily': round(p['sharpe_daily'], 2),
        'bootstrap_p_lockbox': round(p['bootstrap_p'], 4),
        'boot_ci_lo_$25_lockbox': round(p['boot_ci_lo_$25'], 2),
        'boot_ci_hi_$25_lockbox': round(p['boot_ci_hi_$25'], 2),
        'fires_per_day': round(p['fires_per_day'], 2),
        'days_lock': p['days_lock'],
        'v6_score': round(p['v6_score'], 2),
        'conviction_method': 'B (empirical WR per # extras passing, train+val); deploy=Hybrid max(half-Kelly, linear-conviction)',
    }
    top5_rows.append(row)

top5_df = pd.DataFrame(top5_rows)
top5_df.to_csv(f"{OUT}/top_5_candidates_v6.csv", index=False)
log(f"WROTE top_5_candidates_v6.csv ({len(top5_df)} rows)")

# =========================================================
# 8. Save kelly_results metadata
# =========================================================
kelly_meta = {sid: {
    'core': res['core'], 'extras': res['extras'],
    'bucket_stats': res['bucket_stats'],
    'sum_const_lock':         res['sum_const_lock'],
    'sum_quarter_kelly_lock': res['sum_quarter_kelly_lock'],
    'sum_half_kelly_lock':    res['sum_half_kelly_lock'],
    'sum_linear_lock':        res['sum_linear_lock'],
    'sum_hybrid_lock':        res['sum_hybrid_lock'],
    'sum_const_full':         res['sum_const_full'],
    'sum_quarter_kelly_full': res['sum_quarter_kelly_full'],
    'sum_half_kelly_full':    res['sum_half_kelly_full'],
    'sum_linear_full':        res['sum_linear_full'],
    'sum_hybrid_full':        res['sum_hybrid_full'],
    'n_lock': res['n_lock'], 'n_full': res['n_full'],
    'sum_core_const_lock':         res['sum_core_const_lock'],
    'sum_core_quarter_kelly_lock': res['sum_core_quarter_kelly_lock'],
    'sum_core_hybrid_lock':        res['sum_core_hybrid_lock'],
    'sum_core_linear_lock':        res['sum_core_linear_lock'],
    'sum_core_const_full':         res['sum_core_const_full'],
    'sum_core_quarter_kelly_full': res['sum_core_quarter_kelly_full'],
    'sum_core_hybrid_full':        res['sum_core_hybrid_full'],
    'sum_core_linear_full':        res['sum_core_linear_full'],
    'n_core_lock': res['n_core_lock'], 'n_core_full': res['n_core_full'],
} for sid, res in kelly_results.items()}
with open(f"{OUT}/kelly_meta.json", 'w') as f:
    json.dump(kelly_meta, f, indent=2)
log("WROTE kelly_meta.json")
log("DONE")
