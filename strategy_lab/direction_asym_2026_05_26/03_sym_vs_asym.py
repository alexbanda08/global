"""
Fair symmetric vs asymmetric comparison.

Symmetric stack = greedy stack found on TRAIN with UP+DOWN combined (one stack
applied to both directions).
Asymmetric stack = direction-specific greedy stacks (from per-sleeve csv).

Compare both on LOCKBOX with matched gate budget (greedy depth=3).

Also: TASK 4 (threshold-asymmetric on continuous features),
      TASK 5 (DOWN-only / UP-only specialty sleeves),
      TASK 6 (KILL gates per direction).
"""
import pandas as pd
import numpy as np
import os, sys
from pathlib import Path

PANEL = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"
OUTDIR = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/direction_asym_2026_05_26")

print("[load]...")
df = pd.read_parquet(PANEL)
df['fire_date_only'] = df['fire_date'].dt.date
LOCKBOX_START = pd.Timestamp("2026-05-21", tz="UTC").date()

ALL_GATES = [c for c in df.columns if c.startswith("g_")]
for g in ALL_GATES:
    df[g] = df[g].fillna(0).astype(np.int8)

def stack_mask(sub, stack):
    if not stack:
        return np.ones(len(sub), dtype=bool)
    m = np.ones(len(sub), dtype=bool)
    for g in stack:
        m &= (sub[g].values == 1)
    return m

def metrics(sub, mask):
    s = sub[mask]
    n = len(s)
    if n == 0:
        return dict(n=0, WR=np.nan, dpt=np.nan, sum=0.0)
    return dict(n=int(n), WR=float(s['won_int'].mean()),
                dpt=float(s['pnl_legacy_usd'].mean()),
                sum=float(s['pnl_legacy_usd'].sum()))

def bootstrap_p(pnl_arr, n_iter=500, seed=42):
    if len(pnl_arr) < 5:
        return 1.0
    obs = pnl_arr.mean()
    rng = np.random.default_rng(seed)
    nz = pnl_arr - pnl_arr.mean()
    sim = []
    for _ in range(n_iter):
        flips = rng.choice([-1, 1], size=len(nz))
        sim.append((nz * flips).mean())
    sim = np.array(sim)
    return float((sim >= obs).mean())

def greedy(sub_train, gates, max_depth=3, min_n=100):
    best = []
    best_score = sub_train['pnl_legacy_usd'].sum()
    while len(best) < max_depth:
        improved = False
        best_g = None
        for g in gates:
            if g in best:
                continue
            tm = stack_mask(sub_train, best + [g])
            if tm.sum() < min_n:
                continue
            s = sub_train.loc[tm, 'pnl_legacy_usd'].sum()
            if s > best_score:
                best_score = s
                best_g = g
                improved = True
        if improved:
            best.append(best_g)
        else:
            break
    return best

# Load asymmetric optimal stacks from prior run
asym_df = pd.read_csv(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/direction_asymmetric_stacks.csv")
asym_lookup = {}
for _, r in asym_df.iterrows():
    stack = [g for g in str(r['stack']).split('&') if g]
    asym_lookup[(r['sleeve_id'], r['direction'])] = stack

sleeves = list(set(asym_df['sleeve_id']))
print(f"top {len(sleeves)} sleeves")

# --- Symmetric greedy on combined UP+DOWN ---
rows = []
for sleeve in sleeves:
    s_full = df[df['sleeve_id'] == sleeve].copy()
    train = s_full[s_full['fire_date_only'] < LOCKBOX_START]
    lock = s_full[s_full['fire_date_only'] >= LOCKBOX_START]
    # Symmetric: greedy on combined train
    sym_stack = greedy(train, ALL_GATES, max_depth=3, min_n=200)
    m_tr = stack_mask(train, sym_stack)
    m_lk = stack_mask(lock, sym_stack)
    sym_tr = metrics(train, m_tr)
    sym_lk = metrics(lock, m_lk)
    sym_pnl_lk = lock.loc[m_lk, 'pnl_legacy_usd'].values
    sym_p = bootstrap_p(sym_pnl_lk) if len(sym_pnl_lk) >= 20 else np.nan
    # Asymmetric: UP and DOWN stacks applied independently
    up_stack = asym_lookup.get((sleeve, 'UP'), [])
    dn_stack = asym_lookup.get((sleeve, 'DOWN'), [])
    s_up = lock[lock['direction'] == 'UP']
    s_dn = lock[lock['direction'] == 'DOWN']
    m_up = stack_mask(s_up, up_stack)
    m_dn = stack_mask(s_dn, dn_stack)
    asym_pnl = np.concatenate([s_up.loc[m_up, 'pnl_legacy_usd'].values,
                                s_dn.loc[m_dn, 'pnl_legacy_usd'].values])
    asym_won = np.concatenate([s_up.loc[m_up, 'won_int'].values,
                                s_dn.loc[m_dn, 'won_int'].values])
    a_n = len(asym_pnl)
    asym_p = bootstrap_p(asym_pnl) if a_n >= 20 else np.nan
    rows.append(dict(
        sleeve=sleeve,
        sym_stack='&'.join(sym_stack),
        sym_n_train=sym_tr['n'], sym_sum_train=round(sym_tr['sum'],1),
        sym_n_lock=sym_lk['n'], sym_WR_lock=round(sym_lk['WR'],4),
        sym_dpt_lock=round(sym_lk['dpt'],3), sym_sum_lock=round(sym_lk['sum'],1),
        sym_p=round(sym_p,4) if not np.isnan(sym_p) else np.nan,
        up_stack='&'.join(up_stack), dn_stack='&'.join(dn_stack),
        asym_n_lock=a_n,
        asym_WR_lock=round(asym_won.mean(),4) if a_n>0 else np.nan,
        asym_dpt_lock=round(asym_pnl.mean(),3) if a_n>0 else np.nan,
        asym_sum_lock=round(asym_pnl.sum(),1),
        asym_p=round(asym_p,4) if not np.isnan(asym_p) else np.nan,
        delta_WR=round((asym_won.mean() - sym_lk['WR'])*100, 2) if a_n>0 and sym_lk['n']>0 else np.nan,
        delta_dpt=round(asym_pnl.mean() - sym_lk['dpt'], 3) if a_n>0 and sym_lk['n']>0 else np.nan,
    ))

cmp_df = pd.DataFrame(rows)
cmp_df.to_csv(OUTDIR / "sym_vs_asym_fair.csv", index=False)
print(cmp_df[['sleeve','sym_n_lock','sym_WR_lock','sym_dpt_lock','sym_sum_lock','asym_n_lock','asym_WR_lock','asym_dpt_lock','asym_sum_lock','delta_WR','delta_dpt']].to_string())
print(f"\nwrote {OUTDIR/'sym_vs_asym_fair.csv'}")

# --- TASK 3: which gates differ between UP and DOWN ---
shared_gates = {}
up_only = {}
dn_only = {}
for sleeve in sleeves:
    up_s = set(asym_lookup.get((sleeve, 'UP'), []))
    dn_s = set(asym_lookup.get((sleeve, 'DOWN'), []))
    shared_gates[sleeve] = up_s & dn_s
    up_only[sleeve] = up_s - dn_s
    dn_only[sleeve] = dn_s - up_s

# Cross-sleeve gate frequency
from collections import Counter
up_count = Counter()
dn_count = Counter()
shared_count = Counter()
for s in sleeves:
    for g in up_only[s]: up_count[g] += 1
    for g in dn_only[s]: dn_count[g] += 1
    for g in shared_gates[s]: shared_count[g] += 1

print("\n--- TASK 3: Gate occurrence across sleeves ---")
print("UP-only (gate appears in UP stack but not in matching DOWN stack):")
for g, c in sorted(up_count.items(), key=lambda x:-x[1]):
    print(f"  {c}x  {g}")
print("DOWN-only:")
for g, c in sorted(dn_count.items(), key=lambda x:-x[1]):
    print(f"  {c}x  {g}")
print("BOTH-direction (universal):")
for g, c in sorted(shared_count.items(), key=lambda x:-x[1]):
    print(f"  {c}x  {g}")

# Save
diff_rows = []
for s in sleeves:
    diff_rows.append(dict(sleeve=s,
        shared='&'.join(sorted(shared_gates[s])),
        up_only='&'.join(sorted(up_only[s])),
        dn_only='&'.join(sorted(dn_only[s])),
    ))
pd.DataFrame(diff_rows).to_csv(OUTDIR / "gate_diff_per_sleeve.csv", index=False)
print(f"\nwrote {OUTDIR/'gate_diff_per_sleeve.csv'}")
