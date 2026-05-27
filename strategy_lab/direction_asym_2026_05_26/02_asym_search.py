"""
Direction-asymmetric gate-stack search per top sleeve.

Tasks 1-3: per (sleeve, direction) greedy gate optimization on val window;
            evaluate on lockbox; compare to symmetric baseline.
Task 6: include g_lm_extreme_against as KILL candidate per direction.

Train/Val/Lockbox splits:
- train  : 2026-05-01 .. 2026-05-20  (20 days)
- val    : 2026-05-21 .. 2026-05-27  (7 days)  -> selection window
                                                  (actual data ends 2026-05-25 19:14)
- lockbox: included in val window above since data ends 05-25;
           use last 5 days (05-21 .. 05-25) as lockbox; 05-01..05-20 as train.
- 500-shuffle bootstrap on combined train+lockbox per stack.

Outputs:
- direction_asym_per_sleeve.csv  : per (sleeve, direction) optimal stack metrics
- direction_asym_compare.csv     : symmetric vs asymmetric per sleeve
- direction_asymmetric_stacks.csv (FINAL) : combined deployable specs
"""
import pandas as pd
import numpy as np
import os, json, sys
from pathlib import Path

PANEL = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"
OUTDIR = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/direction_asym_2026_05_26")
RESDIR = Path(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results")
OUTDIR.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(42)

print("[load] panel...")
df = pd.read_parquet(PANEL)

# Split dates: train 05-01..05-20, lockbox 05-21..05-25
df['fire_date_only'] = df['fire_date'].dt.date
LOCKBOX_START = pd.Timestamp("2026-05-21", tz="UTC").date()

mask_train = df['fire_date_only'] < LOCKBOX_START
mask_lockbox = df['fire_date_only'] >= LOCKBOX_START
print(f"train={mask_train.sum()} lockbox={mask_lockbox.sum()}")

# Candidate gates (37 total). Exclude basis/hl gates with near-empty coverage.
ALL_GATES = [c for c in df.columns if c.startswith("g_")]
# Drop gates with <5% non-null coverage
keep_g = []
for g in ALL_GATES:
    cov = df[g].notna().mean()
    if cov > 0.05:
        keep_g.append(g)
print(f"gates kept (cov>5%): {len(keep_g)} / {len(ALL_GATES)}")
print("dropped:", [g for g in ALL_GATES if g not in keep_g])

# Treat NaN as 0 (gate fails) — standard convention for this panel
for g in keep_g:
    df[g] = df[g].fillna(0).astype(np.int8)

# Top 7 sleeves by raw fire count (highest stat power) AND deployable
sleeve_sizes = df['sleeve_id'].value_counts()
TOP_SLEEVES = sleeve_sizes.head(7).index.tolist()
print("\nTOP 7 SLEEVES:")
for s in TOP_SLEEVES:
    print(f"  {sleeve_sizes[s]:>5} - {s}")

# --- helpers ---
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
    return dict(
        n=int(n),
        WR=float(s['won_int'].mean()),
        dpt=float(s['pnl_legacy_usd'].mean()),
        sum=float(s['pnl_legacy_usd'].sum()),
    )

def bootstrap_p(pnl_arr, n_iter=500, seed=42):
    """One-sided p that mean > 0 under shuffle (sign-flip on entries)."""
    if len(pnl_arr) < 5:
        return 1.0
    obs = pnl_arr.mean()
    rng = np.random.default_rng(seed)
    nz = pnl_arr - pnl_arr.mean()  # center; permute signs
    sim = []
    n = len(nz)
    for _ in range(n_iter):
        flips = rng.choice([-1, 1], size=n)
        sim.append((nz * flips).mean())
    sim = np.array(sim)
    return float((sim >= obs).mean())

# --- greedy search per (sleeve, direction) on train; eval on lockbox ---
def greedy_stack(sub_train, max_depth=4, min_n=50, min_dpt=0.5):
    """Forward-add gates that increase sum on train while keeping n >= min_n.
    Selection criterion: sum_pnl maximisation (matches phase prior rounds)."""
    best = []
    best_score = sub_train['pnl_legacy_usd'].sum()
    best_n = len(sub_train)
    base = best_score
    cand = list(keep_g)
    while len(best) < max_depth:
        improved = False
        best_g = None
        best_g_score = best_score
        best_g_n = best_n
        for g in cand:
            if g in best:
                continue
            test_mask = stack_mask(sub_train, best + [g])
            if test_mask.sum() < min_n:
                continue
            s = sub_train.loc[test_mask, 'pnl_legacy_usd'].sum()
            n = test_mask.sum()
            if s > best_g_score:
                best_g_score = s
                best_g = g
                best_g_n = n
                improved = True
        if improved:
            best.append(best_g)
            best_score = best_g_score
            best_n = best_g_n
        else:
            break
    return best, best_score, best_n

# --- main per (sleeve, direction) ---
rows = []
direction_optimals = {}  # (sleeve, dir) -> stack

for sleeve in TOP_SLEEVES:
    s_full = df[df['sleeve_id'] == sleeve].copy()
    for direction in ['UP', 'DOWN']:
        sd = s_full[s_full['direction'] == direction].copy()
        sd_train = sd[sd['fire_date_only'] < LOCKBOX_START]
        sd_lock = sd[sd['fire_date_only'] >= LOCKBOX_START]
        if len(sd_train) < 200:
            print(f"  skip {sleeve} {direction} train_n={len(sd_train)}")
            continue
        # Baseline (no extra gates) on this direction
        base_train = metrics(sd_train, np.ones(len(sd_train), dtype=bool))
        base_lock = metrics(sd_lock, np.ones(len(sd_lock), dtype=bool))
        # Greedy stack on train
        stack, _, _ = greedy_stack(sd_train, max_depth=4, min_n=100)
        m_tr = stack_mask(sd_train, stack)
        m_lk = stack_mask(sd_lock, stack)
        tr_metrics = metrics(sd_train, m_tr)
        lk_metrics = metrics(sd_lock, m_lk)
        # Bootstrap p on lockbox PnL (one-sided > 0)
        lk_pnl = sd_lock.loc[m_lk, 'pnl_legacy_usd'].values
        p_lock = bootstrap_p(lk_pnl) if len(lk_pnl) >= 20 else np.nan
        # Deployable: lockbox n>=30, WR>=60, dpt>0, p<=0.05
        deploy = (lk_metrics['n'] >= 30 and
                  lk_metrics['WR'] >= 0.60 and
                  lk_metrics['dpt'] > 0 and
                  (not np.isnan(p_lock)) and p_lock <= 0.05)
        rows.append(dict(
            sleeve=sleeve, direction=direction,
            stack='&'.join(stack),
            n_stack_train=tr_metrics['n'], WR_train=round(tr_metrics['WR'],4),
            dpt_train=round(tr_metrics['dpt'],3), sum_train=round(tr_metrics['sum'],2),
            n_stack_lock=lk_metrics['n'], WR_lock=round(lk_metrics['WR'],4) if lk_metrics['n']>0 else np.nan,
            dpt_lock=round(lk_metrics['dpt'],3) if lk_metrics['n']>0 else np.nan,
            sum_lock=round(lk_metrics['sum'],2),
            p_lock=round(p_lock,4) if not np.isnan(p_lock) else np.nan,
            n_base_train=base_train['n'], WR_base_train=round(base_train['WR'],4),
            dpt_base_train=round(base_train['dpt'],3), sum_base_train=round(base_train['sum'],2),
            n_base_lock=base_lock['n'],
            WR_base_lock=round(base_lock['WR'],4) if base_lock['n']>0 else np.nan,
            dpt_base_lock=round(base_lock['dpt'],3) if base_lock['n']>0 else np.nan,
            sum_base_lock=round(base_lock['sum'],2),
            deployable=deploy,
        ))
        direction_optimals[(sleeve, direction)] = stack
        print(f"  {direction} {sleeve[:60]:<60} train sum={tr_metrics['sum']:>8.0f} n={tr_metrics['n']:>4} | lock sum={lk_metrics['sum']:>7.0f} n={lk_metrics['n']:>4} WR={(lk_metrics['WR'] or 0)*100:>4.1f}% dpt=${lk_metrics['dpt'] or 0:.2f} p={p_lock if p_lock is not None else np.nan} {'D' if deploy else ''}")

per_sleeve = pd.DataFrame(rows)
per_sleeve.to_csv(OUTDIR / "direction_asym_per_sleeve.csv", index=False)
print(f"\nwrote {OUTDIR/'direction_asym_per_sleeve.csv'}")

# --- TASK 2: symmetric vs asymmetric ---
# For each sleeve: symmetric_base = no extra gates (or use first sleeve stack as baseline anchor)
# Asymmetric: UP applies stack_UP, DOWN applies stack_DOWN
sym_rows = []
for sleeve in TOP_SLEEVES:
    s_full = df[df['sleeve_id'] == sleeve].copy()
    s_lock = s_full[s_full['fire_date_only'] >= LOCKBOX_START]
    # Symmetric baseline: no extra gates
    sym = metrics(s_lock, np.ones(len(s_lock), dtype=bool))
    # Asymmetric: split by direction
    up_stack = direction_optimals.get((sleeve, 'UP'), [])
    dn_stack = direction_optimals.get((sleeve, 'DOWN'), [])
    s_up = s_lock[s_lock['direction'] == 'UP']
    s_dn = s_lock[s_lock['direction'] == 'DOWN']
    m_up = stack_mask(s_up, up_stack)
    m_dn = stack_mask(s_dn, dn_stack)
    asym_pnl = np.concatenate([s_up.loc[m_up, 'pnl_legacy_usd'].values,
                                s_dn.loc[m_dn, 'pnl_legacy_usd'].values])
    asym_won = np.concatenate([s_up.loc[m_up, 'won_int'].values,
                                s_dn.loc[m_dn, 'won_int'].values])
    a_n = len(asym_pnl)
    sym_rows.append(dict(
        sleeve=sleeve,
        sym_n=sym['n'], sym_WR=round(sym['WR'],4), sym_dpt=round(sym['dpt'],3),
        sym_sum=round(sym['sum'],2),
        asym_n=a_n,
        asym_WR=round(asym_won.mean(),4) if a_n>0 else np.nan,
        asym_dpt=round(asym_pnl.mean(),3) if a_n>0 else np.nan,
        asym_sum=round(asym_pnl.sum(),2) if a_n>0 else 0.0,
        up_stack='&'.join(up_stack),
        dn_stack='&'.join(dn_stack),
        gates_diff=set(up_stack).symmetric_difference(dn_stack),
    ))

sym_df = pd.DataFrame(sym_rows)
sym_df.to_csv(OUTDIR / "direction_asym_compare.csv", index=False)
print(f"\nwrote {OUTDIR/'direction_asym_compare.csv'}")
print(sym_df[['sleeve','sym_n','sym_sum','sym_WR','asym_n','asym_sum','asym_WR']].to_string())

# --- save final stacks ---
final_rows = []
for (sleeve, direction), stack in direction_optimals.items():
    final_rows.append(dict(sleeve_id=sleeve, direction=direction,
                            stack='&'.join(stack), n_gates=len(stack)))
final_df = pd.DataFrame(final_rows)
final_df.to_csv(RESDIR / "direction_asymmetric_stacks.csv", index=False)
print(f"\nwrote {RESDIR/'direction_asymmetric_stacks.csv'}")
print(final_df.to_string())
