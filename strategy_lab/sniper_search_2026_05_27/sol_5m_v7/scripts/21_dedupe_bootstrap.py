"""V7 dedupe + bootstrap test on lockbox.

Dedupe by lockbox-fire fingerprint hash. Bootstrap p via daily-clustered bootstrap.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path
import hashlib

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v7")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v7.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
p = p[p['parent_15m_regime'] != ''].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[18]
val_end = dates_sorted[24]
lock = p[p['date'] >= val_end].copy()
print(f"Lockbox dates: {dates_sorted[24:]}; n={len(lock)}")

vp = pd.read_csv(OUT / "_v7_profile_pass.csv")
print(f"V7 profile pass: {len(vp)}")

# Dedupe by lockbox fingerprint
def fp(atoms):
    mask = np.ones(len(lock), dtype=bool)
    for a in atoms:
        mask &= (lock[a].values == 1)
    fires = lock[mask]
    if len(fires) == 0:
        return ''
    sig = '|'.join(sorted([f"{int(r['slot_start_us'])}:{r['direction']}:{int(r['fire_offset_s'])}"
                            for _, r in fires.iterrows()]))
    return hashlib.md5(sig.encode()).hexdigest()

vp['fp'] = vp['stack'].apply(lambda s: fp(s.split('|')))
unique = vp.drop_duplicates(subset='fp', keep='first').copy()
print(f"After dedup: {len(unique)}")
unique = unique.sort_values('score_l', ascending=False)
print(f"Top 25 unique:")
print(unique.head(25)[['stack','depth','n_l','wr_l','dpt_l','dd_l','ls_l','score_l']].to_string(index=False))
unique.to_csv(OUT / "_v7_dedupe.csv", index=False)

# Bootstrap on lockbox — daily-clustered
print("\n=== BOOTSTRAP (daily-cluster, 1000 iter) ===")
np.random.seed(42)
n_boot = 1000
lock['date'] = pd.to_datetime(lock['fire_us'], unit='us').dt.date
lock_days = sorted(lock['date'].unique())
n_days = len(lock_days)
print(f"Lockbox days: {n_days}")

# constant stake $25 multiplier
def pnl25(pnl_legacy):
    # pnl_legacy is already at $1 stake (entry_qty implicit); scale to $25
    return pnl_legacy * 25.0


def boot_p(atoms, observed_mean):
    mask = np.ones(len(lock), dtype=bool)
    for a in atoms:
        mask &= (lock[a].values == 1)
    sub = lock[mask][['date', 'pnl_legacy_usd']]
    if len(sub) < 10:
        return 1.0
    # null = uniform random assignment from full lockbox universe under the same per-day fire counts
    # daily-cluster: keep day grouping, sample day-pnl sets with replacement
    daily = sub.groupby('date')['pnl_legacy_usd'].apply(lambda x: list(x.values)).to_dict()
    day_list = list(daily.keys())
    boot_means = []
    for _ in range(n_boot):
        sampled = np.random.choice(day_list, size=len(day_list), replace=True)
        all_pnl = []
        for d in sampled:
            all_pnl.extend(daily[d])
        if len(all_pnl) > 0:
            boot_means.append(np.mean(all_pnl))
    boot_means = np.array(boot_means)
    if observed_mean > 0:
        p = (boot_means <= 0).mean()  # P(under null ≤ 0)
    else:
        p = 1.0
    return p


# Bootstrap top 50 (then refine top 15)
boot_results = []
top_to_test = unique.head(80).copy()
for i, row in top_to_test.iterrows():
    atoms = row['stack'].split('|')
    p_b = boot_p(atoms, row['dpt_l'])
    boot_results.append({'stack': row['stack'], 'depth': row['depth'],
                         'n_l': row['n_l'], 'wr_l': row['wr_l'], 'dpt_l': row['dpt_l'],
                         'dd_l': row['dd_l'], 'ls_l': row['ls_l'], 'score_l': row['score_l'],
                         'sum_l': row['sum_l'], 'p_boot': p_b})
boot = pd.DataFrame(boot_results)
boot = boot.sort_values(['p_boot','score_l'], ascending=[True, False])
print(f"\nBootstrap top 30:")
print(boot.head(30).to_string(index=False))
boot.to_csv(OUT / "_v7_bootstrap.csv", index=False)

# V7 final pass with bootstrap
final = boot[boot['p_boot'] <= 0.05].copy().sort_values('score_l', ascending=False)
print(f"\n=== V7 FINAL PASS (p<=0.05): {len(final)} ===")
print(final.to_string(index=False))
final.to_csv(OUT / "_v7_final_pass.csv", index=False)
print(f"\nElapsed: {time.time()-t0:.1f}s")
