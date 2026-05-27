"""TASK 2 + 3 + 4 — Combinatorial gate-stack search with strict 3-way validation.

For each top sleeve cell:
  1. Greedy forward stepwise (add gate that improves train_sum_pnl most).
  2. Backward elimination (remove gate whose removal improves train_sum_pnl).
  3. Exhaustive 2^k on top-12 surviving gates.
  4. Strict validation: train (May 1-14), val (May 14-21), lockbox (May 21-25).
  5. Bootstrap p (500 shuffles) on lockbox.

Output:
  data/v4/canonical/_results/master_combinatorial_results.csv
  data/v4/canonical/_results/master_combinatorial_deployable.csv
"""
import os, time, sys, itertools, json
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
FP = f"{RES}/master_gate_features.parquet"
OUT_ALL = f"{RES}/master_combinatorial_results.csv"
OUT_DEP = f"{RES}/master_combinatorial_deployable.csv"
OUT_DEPTH = f"{RES}/master_combinatorial_by_depth.csv"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading master")
df = pd.read_parquet(FP)
log(f"rows={len(df):,} cols={len(df.columns)}")

# date column for split
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"date range: {df['fire_date'].min()} -> {df['fire_date'].max()}")

# splits — May 1-14 train, May 14-21 val, May 21-25 lockbox
TRAIN_START = pd.Timestamp('2026-05-01', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-05-14', tz='UTC')
VAL_END     = pd.Timestamp('2026-05-21', tz='UTC')
LOCK_END    = pd.Timestamp('2026-05-26', tz='UTC')

def split_masks(d):
    m_train = (d['fire_date'] >= TRAIN_START) & (d['fire_date'] < TRAIN_END)
    m_val   = (d['fire_date'] >= TRAIN_END)   & (d['fire_date'] < VAL_END)
    m_lock  = (d['fire_date'] >= VAL_END)     & (d['fire_date'] < LOCK_END)
    return m_train, m_val, m_lock

m_train, m_val, m_lock = split_masks(df)
log(f"train n={m_train.sum():,}  val n={m_val.sum():,}  lock n={m_lock.sum():,}")

# All gates
ALL_GATES = sorted([c for c in df.columns if c.startswith('g_')])
log(f"{len(ALL_GATES)} gates available")

# Define top sleeves to test — based on master spec.
# We use master_5m/15m panel which already has direction & pnl.
# Apply sleeve filters by asset, tf, offset_s range.
SLEEVES = {
    # 5m sleeves (S6 = spike entry, S15 = anchored vwap; offsets per spec)
    'BTC_5m_60_150':  {'asset': 'BTC', 'tf': '5m', 'off_lo': 60,  'off_hi': 150},  # S6
    'ETH_5m_60_150':  {'asset': 'ETH', 'tf': '5m', 'off_lo': 60,  'off_hi': 150},
    'SOL_5m_60_150':  {'asset': 'SOL', 'tf': '5m', 'off_lo': 60,  'off_hi': 150},
    'BTC_5m_150_240': {'asset': 'BTC', 'tf': '5m', 'off_lo': 150, 'off_hi': 240},  # S15
    'ETH_5m_150_240': {'asset': 'ETH', 'tf': '5m', 'off_lo': 150, 'off_hi': 240},
    'SOL_5m_150_240': {'asset': 'SOL', 'tf': '5m', 'off_lo': 150, 'off_hi': 240},
    # 15m sleeves
    'BTC_15m_60_240': {'asset': 'BTC', 'tf': '15m', 'off_lo': 60,  'off_hi': 240},
    'ETH_15m_60_240': {'asset': 'ETH', 'tf': '15m', 'off_lo': 60,  'off_hi': 240},
    'SOL_15m_60_240': {'asset': 'SOL', 'tf': '15m', 'off_lo': 60,  'off_hi': 240},
    'BTC_15m_150_240':{'asset': 'BTC', 'tf': '15m','off_lo': 150, 'off_hi': 240},
    'ETH_15m_150_240':{'asset': 'ETH', 'tf': '15m','off_lo': 150, 'off_hi': 240},
    # 15m late-slot
    'BTC_15m_480_840':{'asset': 'BTC','tf':'15m','off_lo':480,'off_hi':840},
}

def base_mask(d, spec):
    return (d['asset'] == spec['asset']) & (d['tf'] == spec['tf']) & \
           (d['fire_offset_s'] >= spec['off_lo']) & (d['fire_offset_s'] <= spec['off_hi'])

def gate_passes(d, gates):
    """Return boolean mask: row passes ALL gates (NaN treated as inactive = passes)."""
    if not gates:
        return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        col = d[g].values
        # NaN -> True (gate inactive, doesn't block), 1 -> True, 0 -> False
        m &= (np.isnan(col) | (col == 1))
    return m

def metrics(d, gates):
    m = gate_passes(d, gates)
    sub = d[m]
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, pt=np.nan, sum=0.0)
    wr = sub['won_int'].mean() * 100
    pt = sub['pnl_legacy_usd'].mean()
    s = sub['pnl_legacy_usd'].sum()
    return dict(n=n, wr=wr, pt=pt, sum=s)

def bootstrap_p(d_lock, gates, n_shuffles=500, seed=42):
    """Permutation p — shuffle outcomes (won) and recompute $/tr on lock subset, compare to observed."""
    m = gate_passes(d_lock, gates)
    sub = d_lock[m]
    if len(sub) < 30:
        return np.nan
    obs_pt = sub['pnl_legacy_usd'].mean()
    rng = np.random.default_rng(seed)
    # shuffle pnl_legacy_usd within sub (under H0: no edge)
    pnl = sub['pnl_legacy_usd'].values
    n = len(pnl)
    # bootstrap (sample with replacement, recompute mean)
    cnt = 0
    for _ in range(n_shuffles):
        sample = rng.choice(pnl, size=n, replace=True)
        if sample.mean() >= obs_pt:
            cnt += 1
    return cnt / n_shuffles

def greedy_forward(d_train, candidates, max_k=12, min_n=30):
    """Add gates one at a time, max train sum_pnl, require min_n."""
    chosen = []
    available = list(candidates)
    base = metrics(d_train, chosen)
    best_sum = base['sum']
    for step in range(max_k):
        best_g = None
        best_s = best_sum
        best_pt = -np.inf
        for g in available:
            trial = chosen + [g]
            mt = metrics(d_train, trial)
            if mt['n'] < min_n:
                continue
            # rank by $/tr (resists overfit to n)
            if mt['pt'] > best_pt:
                best_pt = mt['pt']
                best_s = mt['sum']
                best_g = g
        if best_g is None:
            break
        chosen.append(best_g)
        available.remove(best_g)
        best_sum = best_s
    return chosen

def backward_elim(d_train, chosen, min_n=30):
    """Remove a gate if removal raises $/tr."""
    if len(chosen) <= 1:
        return chosen
    cur = list(chosen)
    base_m = metrics(d_train, cur)
    if base_m['n'] < min_n:
        return cur
    cur_pt = base_m['pt']
    changed = True
    while changed and len(cur) > 1:
        changed = False
        for g in list(cur):
            trial = [x for x in cur if x != g]
            mt = metrics(d_train, trial)
            if mt['n'] >= min_n and mt['pt'] > cur_pt + 1e-6:
                cur = trial
                cur_pt = mt['pt']
                changed = True
                break
    return cur

def exhaustive_top_k(d_train, candidates, k=12, max_combo=8, min_n=30):
    """Exhaustive search over best k candidate gates, up to depth max_combo.
    Returns top stack by train $/tr."""
    if not candidates:
        return [], -np.inf
    pool = candidates[:k]
    best_stack = []
    best_pt = -np.inf
    # enumerate combos depth 1..max_combo
    for depth in range(1, min(max_combo, len(pool)) + 1):
        for combo in itertools.combinations(pool, depth):
            mt = metrics(d_train, list(combo))
            if mt['n'] < min_n: continue
            if mt['pt'] > best_pt:
                best_pt = mt['pt']
                best_stack = list(combo)
    return best_stack, best_pt

# Per sleeve, find best stack
results = []
depth_results = []  # k vs best stack at each depth

for sleeve_name, spec in SLEEVES.items():
    log(f"--- sleeve {sleeve_name} ---")
    d_s = df[base_mask(df, spec)].copy()
    if len(d_s) < 100:
        log(f"  skip n={len(d_s)}")
        continue
    mt_train, mt_val, mt_lock = split_masks(d_s)
    d_train = d_s[mt_train]
    d_val = d_s[mt_val]
    d_lock = d_s[mt_lock]
    if len(d_train) < 100 or len(d_lock) < 30:
        log(f"  skip train={len(d_train)} lock={len(d_lock)}")
        continue
    log(f"  n_total={len(d_s):,}  train={len(d_train):,}  val={len(d_val):,}  lock={len(d_lock):,}")

    # baseline (no gates)
    base_train = metrics(d_train, [])
    base_lock = metrics(d_lock, [])
    log(f"  baseline train: n={base_train['n']} WR={base_train['wr']:.2f}% pt=${base_train['pt']:+.3f}")
    log(f"  baseline lock:  n={base_lock['n']} WR={base_lock['wr']:.2f}% pt=${base_lock['pt']:+.3f}")

    # Step 1: greedy forward to k=12
    greedy_stack = greedy_forward(d_train, ALL_GATES, max_k=12, min_n=30)
    log(f"  greedy stack ({len(greedy_stack)}): {greedy_stack}")

    # Track depth curve
    for k in range(1, min(len(greedy_stack)+1, 9)):
        st = greedy_stack[:k]
        m_tr = metrics(d_train, st)
        m_va = metrics(d_val, st)
        m_lo = metrics(d_lock, st)
        depth_results.append(dict(
            sleeve=sleeve_name, depth=k, stack='&'.join(st),
            train_n=m_tr['n'], train_wr=m_tr['wr'], train_pt=m_tr['pt'], train_sum=m_tr['sum'],
            val_n=m_va['n'], val_wr=m_va['wr'], val_pt=m_va['pt'], val_sum=m_va['sum'],
            lock_n=m_lo['n'], lock_wr=m_lo['wr'], lock_pt=m_lo['pt'], lock_sum=m_lo['sum'],
        ))

    # Step 2: backward elimination
    elim_stack = backward_elim(d_train, greedy_stack, min_n=30)
    log(f"  after elim ({len(elim_stack)}): {elim_stack}")

    # Step 3: exhaustive over union of greedy + top-12 single-gate winners
    # Get top-12 single-gate winners on this sleeve
    single_gate_pt = []
    for g in ALL_GATES:
        mt = metrics(d_train, [g])
        if mt['n'] >= 30:
            single_gate_pt.append((g, mt['pt'], mt['n']))
    single_gate_pt.sort(key=lambda x: x[1], reverse=True)
    top12 = [g for g,_,_ in single_gate_pt[:12]]
    union_pool = list(dict.fromkeys(elim_stack + top12))[:12]  # union dedup, cap 12
    log(f"  exhaustive pool ({len(union_pool)}): {union_pool}")

    exh_stack, exh_pt = exhaustive_top_k(d_train, union_pool, k=12, max_combo=8, min_n=30)
    log(f"  exhaustive best ({len(exh_stack)}) train_pt=${exh_pt:+.3f}: {exh_stack}")

    # Score all three candidates on val/lock and pick best by val_pt
    candidates = {
        'greedy': greedy_stack,
        'elim': elim_stack,
        'exhaustive': exh_stack,
    }
    scored = []
    for name, st in candidates.items():
        m_tr = metrics(d_train, st)
        m_va = metrics(d_val, st)
        m_lo = metrics(d_lock, st)
        scored.append((name, st, m_tr, m_va, m_lo))
    # rank by val_pt
    scored.sort(key=lambda x: (x[3]['pt'] if not np.isnan(x[3]['pt']) else -np.inf), reverse=True)
    winner_name, winner_st, win_tr, win_va, win_lo = scored[0]

    # bootstrap p on lock
    boot_p = bootstrap_p(d_lock, winner_st, n_shuffles=500)

    log(f"  WINNER {winner_name}: depth={len(winner_st)} "
        f"train pt=${win_tr['pt']:+.3f} (n={win_tr['n']}), "
        f"val pt=${win_va['pt']:+.3f} (n={win_va['n']}), "
        f"lock pt=${win_lo['pt']:+.3f} (n={win_lo['n']}), "
        f"boot_p={boot_p:.3f}")

    results.append(dict(
        sleeve=sleeve_name, asset=spec['asset'], tf=spec['tf'],
        off_lo=spec['off_lo'], off_hi=spec['off_hi'],
        method=winner_name, stack='&'.join(winner_st), depth=len(winner_st),
        base_train_n=base_train['n'], base_train_wr=base_train['wr'], base_train_pt=base_train['pt'],
        base_lock_n=base_lock['n'], base_lock_wr=base_lock['wr'], base_lock_pt=base_lock['pt'],
        train_n=win_tr['n'], train_wr=win_tr['wr'], train_pt=win_tr['pt'], train_sum=win_tr['sum'],
        val_n=win_va['n'], val_wr=win_va['wr'], val_pt=win_va['pt'], val_sum=win_va['sum'],
        lock_n=win_lo['n'], lock_wr=win_lo['wr'], lock_pt=win_lo['pt'], lock_sum=win_lo['sum'],
        boot_p=boot_p,
        lift_lock_pt=(win_lo['pt'] - base_lock['pt']) if (not np.isnan(win_lo['pt']) and not np.isnan(base_lock['pt'])) else np.nan,
        # All candidate stacks for diagnostics
        greedy_stack='&'.join(greedy_stack),
        elim_stack='&'.join(elim_stack),
        exhaustive_stack='&'.join(exh_stack),
    ))

# Save results
res_df = pd.DataFrame(results)
res_df.to_csv(OUT_ALL, index=False)
log(f"WROTE {OUT_ALL} ({len(res_df)} rows)")

dep_df = res_df[
    (res_df['lock_wr'] >= 65) &
    (res_df['lock_pt'] >= 1.0) &
    (res_df['boot_p'] <= 0.05) &
    (res_df['lock_n'] >= 30)
].copy()
dep_df.to_csv(OUT_DEP, index=False)
log(f"WROTE {OUT_DEP} ({len(dep_df)} deployable rows)")

depth_df = pd.DataFrame(depth_results)
depth_df.to_csv(OUT_DEPTH, index=False)
log(f"WROTE {OUT_DEPTH} ({len(depth_df)} depth rows)")

log("DONE")
