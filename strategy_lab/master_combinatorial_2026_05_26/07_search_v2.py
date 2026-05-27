"""TASK 2-5: Combinatorial gate-stack search on v2 base + COMP-1..6 cross-round tests.

For each base sleeve_id with >= 200 fires (after R1 pre-filter):
  1. Greedy forward (rank by sum_pnl with min_n=30 floor)
  2. Backward elimination
  3. Exhaustive 2^k on top-12 single-gate winners
  4. Strict 3-way validation: train May 1-14, val May 14-21, lock May 21-26
  5. Bootstrap p (500 shuffles) on lockbox

Also test COMP-1..6 cross-round compound stacks.

Outputs:
  master_combinatorial_results_v2.csv
  master_combinatorial_deployable.csv
  master_combinatorial_by_depth.csv
  master_combinatorial_comp_X.csv
"""
import os, time, itertools, json
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
FP = f"{RES}/master_gate_features_v2.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading")
df = pd.read_parquet(FP)
log(f"rows={len(df):,}")

df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
df = df.sort_values('fire_us').reset_index(drop=True)

TRAIN_START = pd.Timestamp('2026-05-01', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-05-14', tz='UTC')
VAL_END     = pd.Timestamp('2026-05-21', tz='UTC')
LOCK_END    = pd.Timestamp('2026-05-26', tz='UTC')

def split_masks(d):
    return (
        (d['fire_date'] >= TRAIN_START) & (d['fire_date'] < TRAIN_END),
        (d['fire_date'] >= TRAIN_END)   & (d['fire_date'] < VAL_END),
        (d['fire_date'] >= VAL_END)     & (d['fire_date'] < LOCK_END),
    )

ALL_GATES = sorted([c for c in df.columns if c.startswith('g_')])
log(f"gates: {len(ALL_GATES)}")

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns:
            # gate not available — treat as inactive (passes for all)
            continue
        col = np.asarray(d[g], dtype=float)
        m &= (np.isnan(col) | (col == 1))
    return m

def metrics(d, gates):
    m = gate_passes(d, gates)
    sub = d[m]
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, pt=np.nan, sum=0.0)
    return dict(n=n,
                wr=sub['won_int'].mean()*100,
                pt=sub['pnl_legacy_usd'].mean(),
                sum=sub['pnl_legacy_usd'].sum())

def bootstrap_p(d_lock, gates, n_shuffles=500, seed=42):
    m = gate_passes(d_lock, gates)
    sub = d_lock[m]
    if len(sub) < 30: return np.nan
    obs = sub['pnl_legacy_usd'].mean()
    rng = np.random.default_rng(seed)
    # H0: shuffle won within the SLEEVE's universe (preserve fire-magnitude distribution)
    # use a basic bootstrap with-replacement test
    pnl = sub['pnl_legacy_usd'].values
    n = len(pnl)
    means = np.empty(n_shuffles)
    for i in range(n_shuffles):
        means[i] = rng.choice(pnl, size=n, replace=True).mean()
    # one-sided p: prob obs >= 0 under bootstrap
    # for permutation-style p, we test "is obs > 0" using bootstrap CI lower bound
    se = means.std()
    if se == 0: return 0.0
    z = obs / se
    from math import erf, sqrt
    p_one = 0.5 * (1 - erf(z / sqrt(2)))
    return max(p_one, 0.001)

def greedy_forward(d_train, candidates, max_k=10, min_n=30, score='sum'):
    chosen = []
    available = list(candidates)
    for step in range(max_k):
        best_g = None
        best_s = -np.inf
        for g in available:
            trial = chosen + [g]
            mt = metrics(d_train, trial)
            if mt['n'] < min_n: continue
            s = mt['pt'] if score == 'pt' else mt['sum']
            if s > best_s:
                best_s = s
                best_g = g
        if best_g is None: break
        chosen.append(best_g)
        available.remove(best_g)
    return chosen

def backward_elim(d_train, chosen, min_n=30, score='sum'):
    if len(chosen) <= 1: return chosen
    cur = list(chosen)
    base = metrics(d_train, cur)
    if base['n'] < min_n: return cur
    cur_s = base['pt'] if score=='pt' else base['sum']
    changed = True
    while changed and len(cur) > 1:
        changed = False
        for g in list(cur):
            trial = [x for x in cur if x != g]
            mt = metrics(d_train, trial)
            if mt['n'] < min_n: continue
            s = mt['pt'] if score=='pt' else mt['sum']
            if s > cur_s + 0.5:  # need meaningful improvement
                cur = trial
                cur_s = s
                changed = True
                break
    return cur

def exhaustive_top_k(d_train, candidates, k=12, max_combo=8, min_n=30, score='sum'):
    if not candidates: return [], -np.inf
    pool = candidates[:k]
    best_stack, best_s = [], -np.inf
    for depth in range(1, min(max_combo, len(pool)) + 1):
        for combo in itertools.combinations(pool, depth):
            mt = metrics(d_train, list(combo))
            if mt['n'] < min_n: continue
            s = mt['pt'] if score=='pt' else mt['sum']
            if s > best_s:
                best_s = s
                best_stack = list(combo)
    return best_stack, best_s

# ---- Build sleeve list: aggregate by base sleeve cell (tf, asset, offset_bin) and keep ALL the rows ----
# Note: each base sleeve_id is already a pre-filtered universe. We want to find the BEST OVERLAY stack on each.
sleeve_groups = df.groupby('sleeve_id').size().reset_index(name='n')
sleeve_groups = sleeve_groups[sleeve_groups['n'] >= 200].sort_values('n', ascending=False).reset_index(drop=True)
log(f"sleeves with >=200 fires: {len(sleeve_groups)}")

# But the gates already in the base sleeve_id should be EXCLUDED from the search pool (avoid double-counting)
def gates_from_sleeve_id(sid):
    parts = sid.split('|')[2]
    return [p.strip() for p in parts.split('&')]

results = []
depth_results = []
log(f"running search on top {min(15, len(sleeve_groups))} sleeves")

for _, row in sleeve_groups.head(15).iterrows():
    sleeve_id = row['sleeve_id']
    d_s = df[df['sleeve_id'] == sleeve_id].copy()
    asset = d_s['asset'].iloc[0]
    tf = d_s['tf'].iloc[0]
    off_bin = d_s['offset_bin'].iloc[0]
    base_gates = gates_from_sleeve_id(sleeve_id)
    pool = [g for g in ALL_GATES if g not in base_gates]

    log(f"--- {sleeve_id[:90]}  n={len(d_s)} ---")
    log(f"  base gates: {base_gates}")
    m_train, m_val, m_lock = split_masks(d_s)
    d_train = d_s[m_train]; d_val = d_s[m_val]; d_lock = d_s[m_lock]
    if len(d_train) < 100 or len(d_lock) < 30:
        log(f"  SKIP train={len(d_train)} lock={len(d_lock)}")
        continue
    log(f"  splits: train={len(d_train)}  val={len(d_val)}  lock={len(d_lock)}")

    base_tr = metrics(d_train, [])
    base_lo = metrics(d_lock, [])
    log(f"  baseline lock: WR={base_lo['wr']:.2f}%  $/tr=${base_lo['pt']:+.3f}")

    greedy = greedy_forward(d_train, pool, max_k=10, min_n=30, score='sum')
    log(f"  greedy({len(greedy)}): {greedy}")
    elim = backward_elim(d_train, greedy, min_n=30, score='sum')
    log(f"  elim({len(elim)}): {elim}")

    # Top-12 single-gate winners on this sleeve
    sg = []
    for g in pool:
        mt = metrics(d_train, [g])
        if mt['n'] >= 30:
            sg.append((g, mt['sum'], mt['n']))
    sg.sort(key=lambda x: x[1], reverse=True)
    top12 = [g for g,_,_ in sg[:12]]
    ux = list(dict.fromkeys(elim + top12))[:12]
    exh, exh_s = exhaustive_top_k(d_train, ux, k=12, max_combo=8, min_n=30, score='sum')
    log(f"  exh({len(exh)}) train_sum={exh_s:+.1f}: {exh}")

    # Depth curve from greedy
    for k in range(1, min(len(greedy)+1, 9)):
        st = greedy[:k]
        m_tr = metrics(d_train, st); m_va = metrics(d_val, st); m_lo = metrics(d_lock, st)
        depth_results.append(dict(
            sleeve=sleeve_id[:120], depth=k, stack='&'.join(st),
            train_n=m_tr['n'], train_wr=m_tr['wr'], train_pt=m_tr['pt'], train_sum=m_tr['sum'],
            val_n=m_va['n'], val_wr=m_va['wr'], val_pt=m_va['pt'], val_sum=m_va['sum'],
            lock_n=m_lo['n'], lock_wr=m_lo['wr'], lock_pt=m_lo['pt'], lock_sum=m_lo['sum'],
        ))

    # Pick best by val_pt
    cands = {'greedy': greedy, 'elim': elim, 'exhaustive': exh}
    scored = []
    for nm, st in cands.items():
        m_va = metrics(d_val, st); m_lo = metrics(d_lock, st)
        v_pt = m_va['pt'] if not np.isnan(m_va['pt']) else -np.inf
        scored.append((nm, st, m_va, m_lo, v_pt))
    scored.sort(key=lambda x: x[4], reverse=True)
    winner_nm, win_st, win_va, win_lo, _ = scored[0]
    win_tr = metrics(d_train, win_st)
    boot_p = bootstrap_p(d_lock, win_st)

    log(f"  WINNER {winner_nm} depth={len(win_st)} "
        f"train WR={win_tr['wr']:.1f}% pt=${win_tr['pt']:+.3f} n={win_tr['n']}, "
        f"val WR={win_va['wr']:.1f}% pt=${win_va['pt']:+.3f} n={win_va['n']}, "
        f"lock WR={win_lo['wr']:.1f}% pt=${win_lo['pt']:+.3f} n={win_lo['n']}, "
        f"boot_p={boot_p:.3f}")

    results.append(dict(
        sleeve_id=sleeve_id[:120], asset=asset, tf=tf, offset_bin=off_bin,
        n_total=len(d_s),
        method=winner_nm, stack='&'.join(win_st), depth=len(win_st),
        base_lock_n=base_lo['n'], base_lock_wr=base_lo['wr'], base_lock_pt=base_lo['pt'],
        train_n=win_tr['n'], train_wr=win_tr['wr'], train_pt=win_tr['pt'], train_sum=win_tr['sum'],
        val_n=win_va['n'], val_wr=win_va['wr'], val_pt=win_va['pt'], val_sum=win_va['sum'],
        lock_n=win_lo['n'], lock_wr=win_lo['wr'], lock_pt=win_lo['pt'], lock_sum=win_lo['sum'],
        boot_p=boot_p,
        lift_lock_pt=(win_lo['pt'] - base_lo['pt']) if (not np.isnan(win_lo['pt']) and not np.isnan(base_lo['pt'])) else np.nan,
        greedy='&'.join(greedy),
        elim='&'.join(elim),
        exhaustive='&'.join(exh),
    ))

pd.DataFrame(results).to_csv(f"{RES}/master_combinatorial_results_v2.csv", index=False)
log(f"WROTE master_combinatorial_results_v2.csv ({len(results)} rows)")

deployable = pd.DataFrame(results)
dep = deployable[(deployable['lock_wr']>=65) & (deployable['lock_pt']>=1.0) &
                 (deployable['boot_p']<=0.05) & (deployable['lock_n']>=30)].copy()
dep.to_csv(f"{RES}/master_combinatorial_deployable.csv", index=False)
log(f"WROTE master_combinatorial_deployable.csv ({len(dep)} deployable)")

pd.DataFrame(depth_results).to_csv(f"{RES}/master_combinatorial_by_depth.csv", index=False)
log(f"WROTE master_combinatorial_by_depth.csv ({len(depth_results)} rows)")

# ---- TASK 5: COMP-1..6 cross-round compound tests ----
log("=== TASK 5 COMP-X cross-round compounds ===")
COMPS = {
    'COMP-1_BTC_S6_mp+lm': dict(
        base_filter=lambda d: (d['asset']=='BTC') & (d['tf']=='5m') & (d['offset_bin']=='60-150') & (d['tf_orig']=='s6_5m'),
        gates=['g_mp_no_extreme','g_lm_high_stat']),
    'COMP-2_BTC_S6_vol+mp': dict(
        base_filter=lambda d: (d['asset']=='BTC') & (d['tf']=='5m') & (d['offset_bin']=='60-150') & (d['tf_orig']=='s6_5m'),
        gates=['g_vol_expanding','g_mp_no_extreme']),
    'COMP-3_ETH_S6_vol+flow+mp': dict(
        base_filter=lambda d: (d['asset']=='ETH') & (d['tf']=='5m') & (d['offset_bin']=='60-150') & (d['tf_orig']=='s6_5m'),
        gates=['g_vol_expanding','g_flow_with_and_no_whale','g_mp_change_with']),
    'COMP-4_BTC_S15_hy+mp+imb': dict(
        base_filter=lambda d: (d['asset']=='BTC') & (d['tf']=='5m') & (d['offset_bin']=='150-240') & (d['tf_orig']=='s15_5m'),
        # no hy_cb_with_dir; substitute g_hawkes_imbalance_with as direction-confirming flow proxy
        gates=['g_hawkes_imbalance_with','g_mp_no_extreme','g_imb_change_with']),
    'COMP-5_15m_trend_strong+mp+nolm': dict(
        base_filter=lambda d: (d['tf']=='15m') & d['tf_orig'].str.contains('v15m'),
        gates=['g_trend_slope_strong_with','g_mp_no_extreme','g_lm_extreme_against']),
        # NOTE: g_lm_extreme_against being TRUE = KILL signal. But our wrapping has
        # gate=True -> pass. So this gate becomes "kill the trade IF jump-against fires";
        # we INVERT it later: include when g_lm_extreme_against != 1
    'COMP-6_BTC_S6_superstack': dict(
        base_filter=lambda d: (d['asset']=='BTC') & (d['tf']=='5m') & (d['offset_bin']=='60-150') & (d['tf_orig']=='s6_5m'),
        gates=['g_cci_with','g_stoch_with','g_rf_with','g_tr_above_ema50','g_ribbon_agrees',
               'g_mp_no_extreme','g_mp_change_with','g_lm_high_stat']),
}
comp_results = []
for name, spec in COMPS.items():
    d_c = df[spec['base_filter'](df)].copy()
    if len(d_c) == 0:
        log(f"{name}: NO ROWS for base filter")
        continue
    # COMP-5: invert g_lm_extreme_against (pass when NOT active)
    if name == 'COMP-5_15m_trend_strong+mp+nolm':
        d_c['g_lm_extreme_against'] = 1.0 - d_c['g_lm_extreme_against'].fillna(0)
    m_train, m_val, m_lock = split_masks(d_c)
    d_train = d_c[m_train]; d_val = d_c[m_val]; d_lock = d_c[m_lock]
    base_lo = metrics(d_lock, [])
    win_tr = metrics(d_train, spec['gates'])
    win_va = metrics(d_val, spec['gates'])
    win_lo = metrics(d_lock, spec['gates'])
    boot_p = bootstrap_p(d_lock, spec['gates'])
    log(f"{name}: base_lock n={base_lo['n']} pt=${base_lo['pt']:+.3f}; "
        f"stack train n={win_tr['n']} pt=${win_tr['pt']:+.3f}, "
        f"val n={win_va['n']} pt=${win_va['pt']:+.3f}, "
        f"lock n={win_lo['n']} WR={win_lo['wr']:.1f}% pt=${win_lo['pt']:+.3f} p={boot_p:.3f}")
    comp_results.append(dict(
        comp=name, gates='&'.join(spec['gates']),
        train_n=win_tr['n'], train_wr=win_tr['wr'], train_pt=win_tr['pt'], train_sum=win_tr['sum'],
        val_n=win_va['n'], val_wr=win_va['wr'], val_pt=win_va['pt'], val_sum=win_va['sum'],
        lock_n=win_lo['n'], lock_wr=win_lo['wr'], lock_pt=win_lo['pt'], lock_sum=win_lo['sum'],
        boot_p=boot_p,
        base_lock_n=base_lo['n'], base_lock_pt=base_lo['pt'],
        lift_lock_pt=(win_lo['pt'] - base_lo['pt']) if (not np.isnan(win_lo['pt']) and not np.isnan(base_lo['pt'])) else np.nan,
    ))

pd.DataFrame(comp_results).to_csv(f"{RES}/master_combinatorial_comp.csv", index=False)
log(f"WROTE master_combinatorial_comp.csv ({len(comp_results)})")
log("DONE")
