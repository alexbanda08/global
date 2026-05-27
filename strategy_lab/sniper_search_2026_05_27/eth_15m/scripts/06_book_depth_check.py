"""Check book depth at $250 for ETH 15m fires.

The brief notes ETH (and ETH 5m) has a $250 fill problem (463 bps slippage).
For ETH 15m sniper sleeves, compute what % of fires have ADEQUATE book depth at $250 stake
so we can flag candidates that have a sub-deployment viability subset.

vol_hurst_at_fire_15m has up_usd, dn_usd columns which give the L25 walk amount.

We measure:
  - For each fire, total USD available on the SIDE we'd buy (direction)
  - g_book_depth_supports_250: total_side_usd >= 250

If a sleeve has high % of fires with this gate, the sleeve is also viable at $250.
If <30% pass, the sleeve is only viable at small stakes ($25).
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m"

vh = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/vol_hurst_at_fire_15m.parquet")
vh = vh[vh.asset=='ETH'].copy()
log(f"vh ETH rows: {len(vh)}; cols sample: up_usd={vh.up_usd.describe()}")
print(vh[['up_usd','dn_usd']].describe())

# Join to enriched fires
df = pd.read_parquet(f"{OUT}/eth_15m_enriched.parquet")
log(f"df rows: {len(df)}")

vh_keep = vh[['slug','fire_us','fire_offset_s','up_usd','dn_usd']].drop_duplicates(['slug','fire_us'])
df2 = df.merge(vh_keep, on=['slug','fire_us','fire_offset_s'], how='left')

# For UP fires use up_usd, for DOWN use dn_usd
df2['side_usd'] = np.where(df2.direction=='UP', df2.up_usd, df2.dn_usd)
df2['g_book_depth_supports_250'] = (df2.side_usd >= 250).fillna(False).astype(int)
log(f"g_book_depth_supports_250 overall ones rate: {df2.g_book_depth_supports_250.mean():.3f}")

# Save augmented
df2.to_parquet(f"{OUT}/eth_15m_enriched_with_bookdepth.parquet", index=False)

# Apply HUR22_k4 stack and check book-depth subset
df2['fire_date'] = pd.to_datetime(df2.fire_us, unit='us', utc=True)
gates = ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high']
m = np.ones(len(df2), dtype=bool)
for g in gates:
    m &= (df2[g].fillna(0).astype(float) == 1).values
sub = df2[m]
log(f"HUR22_k4 fires (full window): {len(sub)}")
log(f"  with g_book_depth_supports_250: {sub.g_book_depth_supports_250.sum()} ({sub.g_book_depth_supports_250.mean()*100:.1f}%)")
sub250 = sub[sub.g_book_depth_supports_250 == 1]
log(f"  side_usd distribution within HUR22_k4:")
print(sub.side_usd.describe())

# Effect on PnL: $250-deployable subset metrics
log("HUR22_k4 metrics on $250-deployable subset:")
print(f"  n={len(sub250)} WR={sub250.won.mean()*100:.1f}% dpt(@\$25)={sub250.pnl_legacy_usd.mean():.2f}")

# All sniper finalist candidates
finalists = {
    'HUR22_k4': ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high'],
    'F10_mpskew_offset_vwap': ['g_mp_skew_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F9_pivot_offset_vwap': ['g_near_pivot','g_offset_early','g_above_1h_dailyvwap_with'],
    'F12_tr_stack_offset_vwap': ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'V1_no_offset_early': ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_vol_high'],
}
print("\n=== $250 deployable subset for each finalist ===")
for n, g in finalists.items():
    m = np.ones(len(df2), dtype=bool)
    for gg in g:
        m &= (df2[gg].fillna(0).astype(float) == 1).values
    sub = df2[m]
    sub250 = sub[sub.g_book_depth_supports_250 == 1]
    n_overall = len(sub); n250 = len(sub250)
    pct = n250 / max(n_overall,1) * 100
    print(f"  {n:30}: n={n_overall:5} | $250-deployable: n={n250:5} ({pct:5.1f}%) | dpt(@\$25)={sub250.pnl_legacy_usd.mean() if n250 else 0:.2f} WR={sub250.won.mean()*100 if n250 else 0:.1f}%")

log("DONE")
