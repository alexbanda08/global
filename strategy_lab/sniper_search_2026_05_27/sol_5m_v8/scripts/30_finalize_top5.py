"""V8 SOL 5m — pick top 5 diversified sleeves, full metrics, PnL plots."""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v8")
PLOTS = OUT / "plots"
PLOTS.mkdir(exist_ok=True)

p = pd.read_parquet(OUT / "_panel_sol_5m_v8.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
days_total = len(dates_sorted)
n_train = int(round(days_total * 0.60))
n_val = int(round(days_total * 0.20))
train_end = dates_sorted[n_train]
val_end = dates_sorted[n_train + n_val]
train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()
days_full = (p['date'].max() - p['date'].min()).days + 1
days_lockbox = (lock['date'].max() - lock['date'].min()).days + 1
days_val = (val['date'].max() - val['date'].min()).days + 1
days_train = (train['date'].max() - train['date'].min()).days + 1
print(f"Splits: train={days_train}d (n={len(train)}), val={days_val}d (n={len(val)}), lockbox={days_lockbox}d (n={len(lock)}), full={days_full}d (n={len(p)})")


def stack_mask(df, atoms):
    m = np.ones(len(df), dtype=bool)
    for a in atoms:
        m &= (df[a].values == 1)
    return m


def eval_one(df, atoms):
    m = stack_mask(df, atoms)
    sub = df[m].sort_values('fire_us')
    if len(sub) == 0:
        return {'n':0,'wr':0,'dpt':0,'dd':0,'ls':0,'sum':0,'sharpe':0,'fires':sub}
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls = 0; cur = 0
    for v in pnl:
        if v < 0:
            cur += 1; ls = max(ls, cur)
        else:
            cur = 0
    sharpe = float(pnl.mean() / pnl.std() * np.sqrt(len(pnl))) if pnl.std() > 0 else 0
    return {'n': len(sub), 'wr': float(sub['won'].mean()), 'dpt': float(pnl.mean()),
            'dd': dd, 'ls': ls, 'sum': float(pnl.sum()), 'sharpe': sharpe, 'fires': sub}


# Load V8 final pass
fp = pd.read_csv(OUT / "_v8_final_pass.csv")
print(f"Final pass total: {len(fp)}")

# Tag stacks by which V8 path they use
def tag(stack):
    tags = []
    if 'g_2asset_' in stack or 'g_3asset_' in stack: tags.append('J_2asset')
    if 'g_tod_' in stack: tags.append('K_TOD')
    if 'g_q_15m_' in stack: tags.append('Q_5m15m')
    if 'g_hl_' in stack: tags.append('O_HL')
    if 'g_btc_' in stack and not tags: tags.append('V7_inherited_C')
    if 'g_hurst_' in stack and not tags: tags.append('V7_inherited_H')
    if 'g_parent_' in stack and not tags: tags.append('V7_inherited_F')
    if not tags: tags.append('V7_baseline')
    return ','.join(tags)

fp['tags'] = fp['stack'].apply(tag)
fp.to_csv(OUT / "_v8_final_pass_tagged.csv", index=False)

# Diversification: pick 5 distinct sleeves preferring V8-path picks
# Pick by: 1) best proj_honest with V8 path, 2) best WR with diff tags, 3) backup picks

candidates_sorted = fp.sort_values('proj_honest', ascending=False).reset_index(drop=True)

# Strategy:
#   S1 = top overall by proj_honest
#   S2 = top with K_TOD anchor and not redundant with S1
#   S3 = top with J_2asset anchor and not redundant
#   S4 = top with V7_inherited paths (legacy hurst+btc winner)
#   S5 = highest WR ($/tr >=4)

def is_redundant(stack_atoms, picked_atoms_list, jaccard_thresh=0.66):
    sa = set(stack_atoms)
    for pa in picked_atoms_list:
        pas = set(pa)
        jac = len(sa & pas) / max(len(sa | pas), 1)
        if jac >= jaccard_thresh:
            return True
    return False

picks = []
picked_atoms = []

def add_pick(row, label):
    atoms = row['stack'].split('|')
    picks.append({'label': label, **row.to_dict()})
    picked_atoms.append(atoms)

# S1: top proj_honest
S1 = candidates_sorted.iloc[0]
add_pick(S1, 'SOL5_V8_S1')

# S2: top with TOD anchor not redundant with S1
tod_cands = candidates_sorted[candidates_sorted['stack'].str.contains('g_tod_')]
for i, row in tod_cands.iterrows():
    if not is_redundant(row['stack'].split('|'), picked_atoms):
        add_pick(row, 'SOL5_V8_S2')
        break

# S3: top with 2-asset/3-asset anchor not redundant
two_a_cands = candidates_sorted[candidates_sorted['stack'].str.contains('g_2asset_|g_3asset_', regex=True)]
for i, row in two_a_cands.iterrows():
    if not is_redundant(row['stack'].split('|'), picked_atoms):
        add_pick(row, 'SOL5_V8_S3')
        break

# S4: top WR with $/tr >= $5 (volume + quality)
high_wr = candidates_sorted[(candidates_sorted['dpt_lockbox'] >= 5.0) & (candidates_sorted['n_lockbox'] >= 50)]
for i, row in high_wr.sort_values('wr_lockbox', ascending=False).iterrows():
    if not is_redundant(row['stack'].split('|'), picked_atoms):
        add_pick(row, 'SOL5_V8_S4')
        break

# S5: highest n_lockbox (volume play)
big_n = candidates_sorted[candidates_sorted['n_lockbox'] >= 100].sort_values('n_lockbox', ascending=False)
for i, row in big_n.iterrows():
    if not is_redundant(row['stack'].split('|'), picked_atoms):
        add_pick(row, 'SOL5_V8_S5')
        break

print(f"\nPicked {len(picks)} sleeves")

# Compute full per-split metrics for each pick
top5_rows = []
for pi, pick in enumerate(picks):
    atoms = pick['stack'].split('|')
    rt = eval_one(train, atoms)
    rv = eval_one(val, atoms)
    rl = eval_one(lock, atoms)
    rf = eval_one(p, atoms)
    proj_32d = rl['dpt'] * (rl['n'] / max(days_lockbox, 1)) * 32.66
    proj_full = rf['dpt'] * (rf['n'] / max(days_full, 1)) * 32.66
    proj_honest = min(proj_32d, proj_full)
    row = {
        'label': pick['label'], 'stack': pick['stack'], 'tags': pick.get('tags', tag(pick['stack'])),
        'n_train': rt['n'], 'n_val': rv['n'], 'n_lockbox': rl['n'], 'n_full': rf['n'],
        'wr_train': rt['wr'], 'wr_val': rv['wr'], 'wr_lockbox': rl['wr'], 'wr_full': rf['wr'],
        'dpt_25_train': rt['dpt'], 'dpt_25_val': rv['dpt'], 'dpt_25_lockbox': rl['dpt'], 'dpt_25_full': rf['dpt'],
        'max_dd_25': rl['dd'], 'loss_streak': rl['ls'], 'sharpe': rl['sharpe'],
        'bootstrap_p_lockbox': pick['boot_p_lockbox'],
        'sum_train': rt['sum'], 'sum_val': rv['sum'], 'sum_lockbox': rl['sum'], 'sum_full': rf['sum'],
        'proj_32d': proj_32d, 'proj_full': proj_full, 'proj_honest': proj_honest,
    }
    top5_rows.append(row)

top5 = pd.DataFrame(top5_rows)
top5.to_csv(OUT / "top_5_candidates_v8.csv", index=False)
print("\n=== TOP 5 V8 SLEEVES ===")
cols = ['label','tags','n_lockbox','wr_lockbox','dpt_25_lockbox','max_dd_25','loss_streak',
        'n_full','wr_full','dpt_25_full','proj_32d','proj_full','proj_honest','bootstrap_p_lockbox']
print(top5[cols].to_string(index=False))


# === PnL plots (full window) ===
print("\nGenerating cumulative PnL plots...")
for pick in picks:
    label = pick['label']
    atoms = pick['stack'].split('|')
    rf = eval_one(p, atoms)
    sub = rf['fires']
    if len(sub) == 0:
        continue
    sub = sub.sort_values('fire_us').copy()
    sub['cum_pnl'] = sub['pnl_legacy_usd'].cumsum()
    sub['ts'] = pd.to_datetime(sub['fire_us'], unit='us')
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(sub['ts'].values, sub['cum_pnl'].values, label=f'cum PnL @ $25', color='blue')
    ax.axvline(pd.Timestamp(train_end), color='gray', linestyle='--', alpha=0.6, label='train end')
    ax.axvline(pd.Timestamp(val_end), color='red', linestyle='--', alpha=0.6, label='val end')
    ax.axhline(0, color='black', alpha=0.5)
    ax.set_title(f"{label} | stack: {pick['stack']}\nfull n={len(sub)}, wr={rf['wr']:.1%}, $/tr={rf['dpt']:.2f}, sum=${rf['sum']:.0f}")
    ax.set_ylabel('Cumulative PnL ($)')
    ax.set_xlabel('Date (UTC)')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out_png = PLOTS / f"cumulative_pnl_{label}.png"
    fig.savefig(out_png, dpi=100)
    plt.close(fig)
    print(f"  wrote {out_png}")


# === Compare to V7 baseline ===
print("\n=== V7 baseline comparison ===")
v7_baseline_atoms = ['g_btc_trend_30m_with', 'g_cci_extreme_with', 'g_hurst_reverting']
present = [a for a in v7_baseline_atoms if a in p.columns]
if len(present) == len(v7_baseline_atoms):
    rt = eval_one(train, v7_baseline_atoms)
    rv = eval_one(val, v7_baseline_atoms)
    rl = eval_one(lock, v7_baseline_atoms)
    rf = eval_one(p, v7_baseline_atoms)
    proj_32d = rl['dpt'] * (rl['n'] / max(days_lockbox, 1)) * 32.66
    proj_full = rf['dpt'] * (rf['n'] / max(days_full, 1)) * 32.66
    print(f"V7 S1 baseline on V8 panel:")
    print(f"  train n={rt['n']} wr={rt['wr']:.1%} $/tr={rt['dpt']:.2f}")
    print(f"  val   n={rv['n']} wr={rv['wr']:.1%} $/tr={rv['dpt']:.2f}")
    print(f"  lockbox n={rl['n']} wr={rl['wr']:.1%} $/tr={rl['dpt']:.2f} dd={rl['dd']:.0f} ls={rl['ls']}")
    print(f"  full n={rf['n']} wr={rf['wr']:.1%} $/tr={rf['dpt']:.2f} sum=${rf['sum']:.0f}")
    print(f"  proj_32d=${proj_32d:.0f} proj_full=${proj_full:.0f}")

# === Path winner analysis ===
print("\n=== Path winner counts in V8 final pass ===")
print(fp['tags'].value_counts().head(20))

# TOD specialization analysis
print("\n=== TOD specialization findings ===")
tod_cands_top = fp[fp['stack'].str.contains('g_tod_')].head(20)
for _, r in tod_cands_top.iterrows():
    tod_atoms = [a for a in r['stack'].split('|') if a.startswith('g_tod_')]
    print(f"  WR={r['wr_lockbox']:.1%} $/tr={r['dpt_lockbox']:.2f} n={r['n_lockbox']} TOD={tod_atoms} stack={r['stack']}")

print("\nDone.")
