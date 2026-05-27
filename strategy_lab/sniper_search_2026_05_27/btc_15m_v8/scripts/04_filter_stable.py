"""Filter to truly stable V8 sleeves: train+val+lock all $/tr > 0, with WR & $/tr targets.
Print top-20 by honest projection, with full per-split metrics + bootstrap p.
Also: TOD-specialization analysis — which TOD bucket has best results."""
import os, sys, time
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading all results")
res = pd.read_csv(f"{OUTDIR}/v8_combinatorial_all.csv")
log(f"  rows: {len(res)}")

# STRICT v8 pass: train+val+lock all > 0
res['v8_strict'] = (
    (res.dpt_train > 0) & (res.dpt_val > 0) & (res.dpt_lock > 0) &
    (res.wr_lock >= 0.55) & (res.dpt_lock >= 4) &
    (res.n_lock >= 5) & (res.n_full >= 30) &
    (res.max_dd_lock >= -500) & (res.loss_streak_lock <= 14)
)

strict = res[res.v8_strict].copy()
log(f"STRICT v8 survivors (train+val+lock all positive): {len(strict)}")

# Rank by honest projection
strict = strict.sort_values('proj_honest', ascending=False)

# Print top 20
print()
print("="*130)
print(f"TOP 20 STRICT V8 BTC 15m SLEEVES (train+val+lock all $/tr > 0, WR_lock>=55%, $/tr_lock>=$4)")
print("="*130)
for _, r in strict.head(20).iterrows():
    print(f"  off={r['off']:3} dir={r['dir']:4} n_gates={r['n_gates']}  "
          f"n_full={r['n_full']:4} n_lock={r['n_lock']:3}  "
          f"WR(t/v/l)=({r['wr_train']:.2f}/{r['wr_val']:.2f}/{r['wr_lock']:.2f})  "
          f"$/tr(t/v/l)=(${r['dpt_train']:+.1f}/${r['dpt_val']:+.1f}/${r['dpt_lock']:+.1f})  "
          f"proj_honest=${r['proj_honest']:+.0f}  ")
    print(f"        gates: {r['gates']}")

# Save strict survivors
strict.to_csv(f"{OUTDIR}/v8_strict_survivors.csv", index=False)

# ============================== TOD SPECIALIZATION ANALYSIS ==============================
print()
print("="*130)
print("TOD SPECIALIZATION ANALYSIS — best sleeves per TOD bucket")
print("="*130)

# Of the strict survivors, which TOD bucket gates appear most?
tod_gates = ['g_tod_asia_morning','g_tod_european_morning','g_tod_us_afternoon','g_tod_us_evening']
for tg in tod_gates:
    sub = strict[strict.gates.str.contains(tg, regex=False)]
    print(f"  Survivors containing {tg}: n={len(sub)}")
    if len(sub) > 0:
        top = sub.head(3)
        for _, r in top.iterrows():
            print(f"    [n_full={r['n_full']:3} WR_l={r['wr_lock']:.2f} $/tr_l=${r['dpt_lock']:+.1f} proj=${r['proj_honest']:+.0f}] {r['gates']}")

# Sleeves that DON'T have TOD gates (i.e., universal)
universal = strict[~strict.gates.str.contains('g_tod_')]
print(f"\n  Universal (no TOD gate): n={len(universal)}")
if len(universal):
    for _, r in universal.head(5).iterrows():
        print(f"    [n_full={r['n_full']:3} WR_l={r['wr_lock']:.2f} $/tr_l=${r['dpt_lock']:+.1f} proj=${r['proj_honest']:+.0f}] {r['gates']}")

# ============================== Path-attribution ==============================
print()
print("="*130)
print("PATH ATTRIBUTION — which V8 path produced the wins?")
print("="*130)

path_gates = {
    'PATH K (TOD)': ['g_tod_'],
    'PATH L (1h grandparent)': ['g_grandparent_1h_'],
    'PATH J (2-asset confluence)': ['g_xa_','g_btc_eth_confluence','g_btc_sol_confluence','g_btc_eth_divergence'],
    'PATH P (liq shock)': ['g_liq_shock','g_liq_calm'],
}
for path, prefixes in path_gates.items():
    sub = strict
    for p in prefixes:
        if not sub.empty:
            # ANY row containing any of these prefixes
            mask = strict.gates.apply(lambda gs: any(p in g for g in gs.split('+')))
            sub_now = strict[mask]
            if len(sub_now) > len(sub):
                sub = sub_now
    # use: any in path
    mask = strict.gates.apply(lambda gs: any(any(p in g for p in prefixes) for g in gs.split('+')))
    n = mask.sum()
    print(f"  {path}: {n} survivor sleeves use this path")
    if n > 0:
        s = strict[mask].head(3)
        for _, r in s.iterrows():
            print(f"    [n_full={r['n_full']:3} WR_l={r['wr_lock']:.2f} $/tr_l=${r['dpt_lock']:+.1f} proj=${r['proj_honest']:+.0f}] {r['gates']}")
print()
log("DONE")
