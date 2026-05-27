"""Dedupe alias stacks, bootstrap top candidates, pick top 5."""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v6")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v6.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[18]
val_end = dates_sorted[24]
train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()


def eval_stack(df, atoms):
    if len(atoms) == 0:
        sub = df
    else:
        mask = np.ones(len(df), dtype=bool)
        for a in atoms:
            mask &= (df[a].values == 1)
        sub = df[mask]
    if len(sub) == 0:
        return 0, 0.0, 0.0, 0.0, 0, 0.0, sub
    sub = sub.sort_values('fire_us')
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0
    cur = 0
    for v in pnl:
        if v < 0:
            cur += 1
            ls_max = max(ls_max, cur)
        else:
            cur = 0
    return len(sub), float(sub['won'].mean()), float(pnl.mean()), dd, ls_max, float(pnl.sum()), sub


# Load V6 profile pass
df = pd.read_csv(OUT / "_v6_profile_pass.csv")
print(f"V6 profile-pass stacks: {len(df)}")

# Dedupe: stacks producing IDENTICAL (n_l, wr_l, dpt_l) tuples are aliases
# Keep canonical = shortest stack within each alias group
df['fingerprint'] = df.apply(lambda r: f"{r['n_l']}_{r['wr_l']:.4f}_{r['dpt_l']:.4f}_{r['dd_l']:.2f}_{r['ls_l']}", axis=1)
df['n_atoms'] = df['stack'].apply(lambda s: len(s.split('|')))
df = df.sort_values(['fingerprint','n_atoms'])
df_dedupe = df.drop_duplicates(subset='fingerprint', keep='first').sort_values('score_l', ascending=False)
print(f"After dedupe by lockbox fingerprint: {len(df_dedupe)}")
df_dedupe.to_csv(OUT / "_v6_dedupe.csv", index=False)

# Show top 20
print("\nTop 20 unique candidates:")
print(df_dedupe.head(20)[['stack','n_atoms','n_tr','wr_tr','dpt_tr','n_v','wr_v','dpt_v','n_l','wr_l','dpt_l','dd_l','ls_l','score_l']].to_string(index=False))


# === Direction-asymmetric variants — wrap top 20 stacks with UP / DOWN filters ===
print("\n=== Direction-asymmetric variants ===")
asymm_rows = []
top20 = df_dedupe.head(20)
for _, r in top20.iterrows():
    base = r['stack'].split('|')
    for dir_atom in ['', 'g_dir_up', 'g_dir_dn']:
        stack = base if dir_atom == '' else base + [dir_atom]
        n_tr, wr_tr, dpt_tr, dd_tr, ls_tr, _, _ = eval_stack(train, stack)
        n_v, wr_v, dpt_v, _, _, _, _ = eval_stack(val, stack)
        n_l, wr_l, dpt_l, dd_l, ls_l, sum_l, _ = eval_stack(lock, stack)
        if n_l < 20: continue
        asymm_rows.append({
            'stack': '|'.join(sorted(stack)), 'dir': dir_atom or 'BOTH',
            'n_tr': n_tr, 'wr_tr': wr_tr, 'dpt_tr': dpt_tr,
            'n_v': n_v, 'wr_v': wr_v, 'dpt_v': dpt_v,
            'n_l': n_l, 'wr_l': wr_l, 'dpt_l': dpt_l, 'dd_l': dd_l, 'ls_l': ls_l, 'sum_l': sum_l,
            'score_l': dpt_l * np.sqrt(n_l) if dpt_l > 0 else 0,
        })
asymm = pd.DataFrame(asymm_rows).sort_values('score_l', ascending=False)
# Filter to V6 bar
asymm_pass = asymm[
    (asymm['n_l'] >= 30) & (asymm['wr_l'] >= 0.65) &
    (asymm['dpt_l'] >= 4.0) & (asymm['dd_l'] <= 500) & (asymm['ls_l'] <= 14)
]
print(f"Asymmetric variants passing V6 bar: {len(asymm_pass)}")
print(asymm_pass.head(20)[['stack','dir','n_tr','wr_tr','dpt_tr','n_l','wr_l','dpt_l','dd_l','ls_l','sum_l','score_l']].to_string(index=False))
asymm.to_csv(OUT / "_asymm_variants.csv", index=False)


# === Bootstrap top 10 candidates ===
def bootstrap_p(pnl_arr, n_iter=1000, seed=42):
    """Daily-clustered bootstrap on PnL. Returns one-sided p (H0: mean<=0)."""
    rng = np.random.default_rng(seed)
    n = len(pnl_arr)
    if n < 5: return 1.0
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        means[i] = pnl_arr[idx].mean()
    # p = fraction of bootstrap means <= 0
    return float((means <= 0).mean())


# Combine: best V6 candidates (both symmetric + asymmetric) + bootstrap
print("\n=== STAGE 7: bootstrap top candidates ===")
candidates = []
# Symmetric (BOTH dir)
for _, r in df_dedupe.head(15).iterrows():
    candidates.append({'stack': r['stack'], 'dir': 'BOTH', 'source': 'symm'})
# Asymmetric — pick best UP and best DOWN distinct
asymm_up = asymm_pass[asymm_pass['dir']=='g_dir_up'].drop_duplicates(subset=['stack']).head(7)
asymm_dn = asymm_pass[asymm_pass['dir']=='g_dir_dn'].drop_duplicates(subset=['stack']).head(7)
for _, r in asymm_up.iterrows():
    candidates.append({'stack': r['stack'], 'dir': 'g_dir_up', 'source': 'asymm_up'})
for _, r in asymm_dn.iterrows():
    candidates.append({'stack': r['stack'], 'dir': 'g_dir_dn', 'source': 'asymm_dn'})
print(f"Candidates to bootstrap: {len(candidates)}")

results = []
for c in candidates:
    atoms = c['stack'].split('|')
    n_tr, wr_tr, dpt_tr, dd_tr, ls_tr, _, _ = eval_stack(train, atoms)
    n_v, wr_v, dpt_v, dd_v, ls_v, _, _ = eval_stack(val, atoms)
    n_l, wr_l, dpt_l, dd_l, ls_l, sum_l, sub_l = eval_stack(lock, atoms)
    if n_l < 20: continue
    p_boot = bootstrap_p(sub_l['pnl_legacy_usd'].values, n_iter=1000)
    # Quick Sharpe approx: daily-aggregated
    daily_sums = sub_l.groupby('date')['pnl_legacy_usd'].sum()
    sharpe_daily = daily_sums.mean() / daily_sums.std() * np.sqrt(252) if daily_sums.std() > 0 else 0
    results.append({
        'stack': c['stack'], 'dir': c['dir'], 'source': c['source'],
        'n_tr': n_tr, 'wr_tr': wr_tr, 'dpt_tr': dpt_tr,
        'n_v': n_v, 'wr_v': wr_v, 'dpt_v': dpt_v,
        'n_l': n_l, 'wr_l': wr_l, 'dpt_l': dpt_l, 'dd_l': dd_l, 'ls_l': ls_l, 'sum_l': sum_l,
        'sharpe_daily': sharpe_daily,
        'bootstrap_p_l': p_boot,
        'score_l': dpt_l * np.sqrt(n_l) if dpt_l > 0 else 0,
    })
df_boot = pd.DataFrame(results).sort_values('score_l', ascending=False)
df_boot.to_csv(OUT / "_bootstrap_results.csv", index=False)

print(f"\nTop 20 bootstrapped:")
print(df_boot.head(20)[['stack','dir','source','n_l','wr_l','dpt_l','dd_l','ls_l','sum_l','sharpe_daily','bootstrap_p_l','score_l']].to_string(index=False))

# Final V6 picks: pass V6 bar AND p<=0.05
final = df_boot[
    (df_boot['n_l'] >= 30) & (df_boot['wr_l'] >= 0.65) &
    (df_boot['dpt_l'] >= 4.0) & (df_boot['dd_l'] <= 500) &
    (df_boot['ls_l'] <= 14) & (df_boot['bootstrap_p_l'] <= 0.05)
]
print(f"\n=== FINAL V6 PASS (p<=0.05): {len(final)} ===")
print(final.head(15)[['stack','dir','source','n_l','wr_l','dpt_l','dd_l','ls_l','sum_l','sharpe_daily','bootstrap_p_l','score_l']].to_string(index=False))
final.to_csv(OUT / "_v6_final_pass.csv", index=False)

print(f"\nElapsed: {time.time()-t0:.1f}s")
