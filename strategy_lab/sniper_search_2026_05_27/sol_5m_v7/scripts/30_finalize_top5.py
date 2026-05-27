"""V7 finalize top 5 — diverse picks by atom family, full metrics + plots."""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v7")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v7.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
p = p[p['parent_15m_regime'] != ''].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[18]
val_end = dates_sorted[24]
train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()
print(f"train: {len(train)}, val: {len(val)}, lockbox: {len(lock)}")

final = pd.read_csv(OUT / "_v7_final_pass.csv")
print(f"Final pass total: {len(final)}")

# Hand-pick top 5 diverse sleeves. Prefer:
#  1. Highest score_l with cross-asset BTC trend (Path C winner)
#  2. Highest WR (lowest p) with HURST variant (Path H)
#  3. Highest n_l with cross-asset BTC f7
#  4. Lowest DD with strong WR
#  5. Best mix of paths

# Tags
def tag(s):
    tags = []
    atoms = s.split('|')
    if any('btc_trend' in a for a in atoms): tags.append('btc_trend')
    if any('btc_f7' in a for a in atoms): tags.append('btc_f7')
    if any('parent_' in a for a in atoms): tags.append('parent')
    if any('hurst' in a for a in atoms): tags.append('hurst')
    if any('vol_v7' in a or 'vol_pct' in a for a in atoms): tags.append('vol')
    if any('f7_v7' in a for a in atoms): tags.append('f7_v7')
    return ','.join(tags) if tags else 'core'
final['tags'] = final['stack'].apply(tag)
final.to_csv(OUT / "_v7_final_pass_tagged.csv", index=False)

# Pick top 5 diverse — fingerprint by stack composition (atom-set hashing)
picks = []
seen_atom_sets = []
def jaccard(a, b):
    s_a = set(a)
    s_b = set(b)
    return len(s_a & s_b) / max(len(s_a | s_b), 1)

for _, r in final.iterrows():
    atoms = set(r['stack'].split('|'))
    too_similar = any(jaccard(atoms, s) > 0.65 for s in seen_atom_sets)
    if too_similar:
        continue
    picks.append(r.to_dict())
    seen_atom_sets.append(atoms)
    if len(picks) >= 5:
        break

picks_df = pd.DataFrame(picks)
print(f"\nDiverse top 5:")
print(picks_df[['stack','tags','depth','n_l','wr_l','dpt_l','dd_l','ls_l','p_boot']].to_string(index=False))


# Full metrics + Sharpe per pick
def eval_full(df, atoms):
    """pnl_legacy_usd is ALREADY at $25 stake."""
    mask = np.ones(len(df), dtype=bool)
    for a in atoms:
        mask &= (df[a].values == 1)
    sub = df[mask].sort_values('fire_us')
    if len(sub) == 0:
        return None
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0; cur = 0
    for v in pnl:
        if v < 0:
            cur += 1; ls_max = max(ls_max, cur)
        else:
            cur = 0
    # Daily Sharpe approx
    sub['date'] = pd.to_datetime(sub['fire_us'], unit='us').dt.date
    daily = sub.groupby('date')['pnl_legacy_usd'].sum()
    if daily.std() == 0 or len(daily) < 2:
        sharpe = 0
    else:
        sharpe = float(daily.mean() / daily.std() * np.sqrt(365))
    # Offset distribution
    offset_dist = sub['fire_offset_s'].value_counts().sort_index().to_dict()
    return {
        'n': len(sub),
        'wr': float(sub['won'].mean()),
        'dpt': float(pnl.mean()),
        'sum': float(pnl.sum()),
        'dd': dd,
        'ls': int(ls_max),
        'sharpe': sharpe,
        'offset_dist': offset_dist,
    }


top5_rows = []
for i, pick in enumerate(picks, 1):
    sid = f"SOL5_V7_S{i}"
    atoms = pick['stack'].split('|')
    m_tr = eval_full(train, atoms)
    m_v = eval_full(val, atoms)
    m_l = eval_full(lock, atoms)
    top5_rows.append({
        'sleeve_id': sid,
        'anchor': 'mixed_offset',
        'gate_stack': pick['stack'],
        'weights': '',
        'conviction_method': 'strict_stack_constant_$25',
        'tags': pick.get('tags',''),
        'n_train': m_tr['n'] if m_tr else 0,
        'n_val': m_v['n'] if m_v else 0,
        'n_lockbox': m_l['n'] if m_l else 0,
        'wr_train': m_tr['wr'] if m_tr else 0,
        'wr_val': m_v['wr'] if m_v else 0,
        'wr_lockbox': m_l['wr'] if m_l else 0,
        'dpt_25_train': m_tr['dpt'] if m_tr else 0,
        'dpt_25_val': m_v['dpt'] if m_v else 0,
        'dpt_25_lockbox': m_l['dpt'] if m_l else 0,
        'sum_25_28d_const': (m_tr['sum'] if m_tr else 0) + (m_v['sum'] if m_v else 0) + (m_l['sum'] if m_l else 0),
        'max_dd_25': m_l['dd'] if m_l else 0,
        'loss_streak': m_l['ls'] if m_l else 0,
        'sharpe': m_l['sharpe'] if m_l else 0,
        'bootstrap_p_lockbox': pick['p_boot'],
        'offset_dist_lockbox': str(m_l['offset_dist']) if m_l else '',
    })
    # Plot cumulative PnL on lockbox
    if m_l:
        mask = np.ones(len(lock), dtype=bool)
        for a in atoms:
            mask &= (lock[a].values == 1)
        sub = lock[mask].sort_values('fire_us')
        pnl = sub['pnl_legacy_usd'].values  # already at $25 stake
        cumsum = np.cumsum(pnl)
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(range(len(cumsum)), cumsum, lw=1.2)
        ax.set_title(f"{sid} lockbox cumulative PnL @ 25 stake | n={m_l['n']} WR={m_l['wr']*100:.1f}% per-tr={m_l['dpt']:.2f}USD DD={m_l['dd']:.0f}USD")
        ax.set_xlabel('trade #')
        ax.set_ylabel('cum PnL (USD)')
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(OUT / 'plots' / f'cumulative_pnl_{sid}.png', dpi=110)
        plt.close(fig)

top5 = pd.DataFrame(top5_rows)
print(f"\n=== TOP 5 V7 SOL 5m ===")
for col in ['wr_train','wr_val','wr_lockbox']:
    top5[col] = top5[col].apply(lambda x: f"{x*100:.1f}%")
print(top5[['sleeve_id','tags','n_train','n_val','n_lockbox','wr_train','wr_val','wr_lockbox','dpt_25_lockbox','max_dd_25','loss_streak','bootstrap_p_lockbox']].to_string(index=False))

# Save CSV (keep numeric)
top5 = pd.DataFrame(top5_rows)
top5.to_csv(OUT / "top_5_candidates_v7.csv", index=False)
print(f"\nWrote top_5_candidates_v7.csv")
print(f"Elapsed: {time.time()-t0:.1f}s")
