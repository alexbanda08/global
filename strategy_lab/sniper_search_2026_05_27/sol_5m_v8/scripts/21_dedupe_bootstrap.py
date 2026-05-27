"""V8 SOL 5m — dedupe near-identical stacks + bootstrap lockbox p-value."""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v8")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v8.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
days_total = len(dates_sorted)
n_train = int(round(days_total * 0.60))
n_val = int(round(days_total * 0.20))
val_end = dates_sorted[n_train + n_val]
lock = p[p['date'] >= val_end].copy()
days_lockbox = (lock['date'].max() - lock['date'].min()).days + 1
days_full = (p['date'].max() - p['date'].min()).days + 1
print(f"Lockbox: {len(lock)} fires, {days_lockbox}d; Full: {len(p)}, {days_full}d")


def stack_mask(df, atoms):
    m = np.ones(len(df), dtype=bool)
    for a in atoms:
        m &= (df[a].values == 1)
    return m


def boot_pvalue(pnl_arr, n_iter=2000, seed=42):
    """One-tailed: P(bootstrap mean <= 0)."""
    if len(pnl_arr) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    n = len(pnl_arr)
    sums = np.zeros(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n, n)
        sums[i] = pnl_arr[idx].mean()
    return float((sums <= 0).mean())


# Load V8 profile pass
profile = pd.read_csv(OUT / "_v8_profile_pass.csv")
print(f"Profile pass: {len(profile)}")

# Dedupe by lockbox fingerprint (set of fire_us hits)
fingerprints = {}
print("Computing lockbox fingerprints...")
for i, row in profile.iterrows():
    atoms = row['stack'].split('|')
    m = stack_mask(lock, atoms)
    fire_set = frozenset(lock.loc[m, 'fire_us'].values.tolist())
    if fire_set in fingerprints:
        # keep the one with higher proj_honest
        if row['proj_honest'] > profile.loc[fingerprints[fire_set], 'proj_honest']:
            fingerprints[fire_set] = i
    else:
        fingerprints[fire_set] = i
keep_idx = list(fingerprints.values())
dedupe = profile.loc[keep_idx].sort_values('proj_honest', ascending=False).reset_index(drop=True)
print(f"After dedupe: {len(dedupe)}")
dedupe.to_csv(OUT / "_v8_dedupe.csv", index=False)


# Bootstrap top 100 by proj_honest
print("\nBootstrapping top 200...")
top200 = dedupe.head(200).copy()
boot_p = []
for i, row in top200.iterrows():
    atoms = row['stack'].split('|')
    m = stack_mask(lock, atoms)
    pnl = lock.loc[m, 'pnl_legacy_usd'].values
    if len(pnl) < 5:
        boot_p.append(1.0)
    else:
        boot_p.append(boot_pvalue(pnl, n_iter=2000, seed=42+i))
top200['boot_p_lockbox'] = boot_p
top200.to_csv(OUT / "_v8_bootstrap.csv", index=False)

# Final pass: bootstrap p <= 0.05
final = top200[top200['boot_p_lockbox'] <= 0.05].copy()
print(f"\n=== V8 FINAL PASS (p<=0.05): {len(final)} ===")
final = final.sort_values('proj_honest', ascending=False).reset_index(drop=True)
final.to_csv(OUT / "_v8_final_pass.csv", index=False)
print(final.head(40)[['stack','n_lockbox','wr_lockbox','dpt_lockbox','dd_lockbox','ls_lockbox',
                       'n_full','wr_full','dpt_full','proj_32d','proj_full','proj_honest','boot_p_lockbox']].to_string(index=False))

print(f"\nElapsed: {time.time()-t0:.1f}s")
