"""
B945 Inventory Sum-Arb Decode
Mission: test operator hypothesis that b945's strategy = temporal sum-arb
(accumulate both sides at combined cost < 1.00 per share-pair via maker+taker).

Run: py strategy_lab/wallet_hunt/_b945_inventory_decode.py
Output:
  - cache/0xb945945d/per_slug_paired_ledger.parquet (Q1 artifact)
  - strategy_lab/reports/B945_INVENTORY_SUMARB_DECODE_2026_06_12.md
"""
import pandas as pd
import numpy as np
import json
import sys
sys.path.insert(0, 'C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical')
from load import load_resolutions

CACHE = 'C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/cache/0xb945945d'
OUT_PARQUET = f'{CACHE}/per_slug_paired_ledger.parquet'
OUT_REPORT = 'C:/Users/alexandre bandarra/Desktop/global/strategy_lab/reports/B945_INVENTORY_SUMARB_DECODE_2026_06_12.md'


# ============================================================
# Q1: Per-slug paired-cost ledger
# ============================================================
print("Loading data...")
ft = pd.read_parquet(f'{CACHE}/fill_tape.parquet')
res = load_resolutions()
res_map = res.set_index('slug')['outcome'].to_dict()

# Per-slug per-outcome aggregate
ps = ft.groupby(['slug', 'outcome']).apply(
    lambda x: pd.Series({
        'n': len(x),
        'sh': x['shares'].sum(),
        'usd': x['usd'].sum(),
        'vwap': (x['price'] * x['shares']).sum() / x['shares'].sum()
    }), include_groups=False
).reset_index()

slug_up = ps[ps['outcome'] == 'Up'].set_index('slug')
slug_dn = ps[ps['outcome'] == 'Down'].set_index('slug')
both = slug_up.join(slug_dn, lsuffix='_up', rsuffix='_dn', how='inner').copy()

both['paired'] = both[['sh_up', 'sh_dn']].min(axis=1)
both['pvs'] = both['vwap_up'] + both['vwap_dn']  # paired vwap sum
both['residual_up'] = both['sh_up'] - both['paired']
both['residual_dn'] = both['sh_dn'] - both['paired']
both['true_outcome'] = both.index.map(res_map)
both['won_up'] = (both['true_outcome'] == 'Up').astype(float)

# PnL components (settled slugs only)
# Winner leg: shares*(1 - entry_price)*(1 - 0.07*entry_price); Loser leg: -shares*entry_price
both['paired_gross'] = np.where(
    both['won_up'] == 1,
    both['paired'] * (1 - both['vwap_up']) * (1 - 0.07 * both['vwap_up'])
    - both['paired'] * both['vwap_dn'],
    np.where(
        both['won_up'] == 0,
        both['paired'] * (1 - both['vwap_dn']) * (1 - 0.07 * both['vwap_dn'])
        - both['paired'] * both['vwap_up'],
        np.nan
    )
)
both['residual_up_pnl'] = np.where(
    both['won_up'] == 1,
    (both['sh_up'] - both['paired']) * (1 - both['vwap_up']) * (1 - 0.07 * both['vwap_up']),
    np.where(both['won_up'] == 0, -(both['sh_up'] - both['paired']) * both['vwap_up'], np.nan)
)
both['residual_dn_pnl'] = np.where(
    both['won_up'] == 0,
    (both['sh_dn'] - both['paired']) * (1 - both['vwap_dn']) * (1 - 0.07 * both['vwap_dn']),
    np.where(both['won_up'] == 1, -(both['sh_dn'] - both['paired']) * both['vwap_dn'], np.nan)
)
both['total_pnl'] = both['paired_gross'] + both['residual_up_pnl'] + both['residual_dn_pnl']

both.to_parquet(OUT_PARQUET)
print(f"Saved per_slug_paired_ledger.parquet: {both.shape}")

both_s = both[both['true_outcome'].notna()].copy()

# Q1 stats
pvs = both_s['pvs']
pg = both_s['paired_gross'].sum()
rp = (both_s['residual_up_pnl'] + both_s['residual_dn_pnl']).sum()
tp = both_s['total_pnl'].sum()
n = len(both_s)

print("\n=== Q1 RESULTS ===")
for t in [1.00, 0.975, 0.97, 0.95, 0.90]:
    print(f"  pvs<{t}: {(pvs < t).mean():.3f}")
print(f"  pvs median: {pvs.median():.4f}, mean: {pvs.mean():.4f}")
print(f"  paired_gross: {pg:.1f} ({pg/n:.2f}/slug)")
print(f"  residual_pnl: {rp:.1f} ({rp/n:.2f}/slug)")
print(f"  total_pnl:    {tp:.1f} ({tp/n:.2f}/slug)")

# ============================================================
# Q2: Side decision rule
# ============================================================
mf = pd.read_parquet(f'{CACHE}/ml_features.parquet')
fills = mf[mf['is_fill'] == 1].copy()
fills['own_ask'] = np.where(fills['side_up'] == 1, fills['up_ask'], fills['dn_ask'])
fills['own_bid'] = np.where(fills['side_up'] == 1, fills['up_bid'], fills['dn_bid'])
fills['opp_ask'] = np.where(fills['side_up'] == 1, fills['dn_ask'], fills['up_ask'])
fills['at_ask'] = (fills['price'] >= fills['own_ask'] - 0.005).astype(float)
fills['at_bid'] = (fills['price'] <= fills['own_bid'] + 0.005).astype(float)
fills['discount'] = fills['own_ask'] - fills['price']
fills['relative_cheap'] = (fills['price'] <= fills['opp_ask']).astype(int)
fills['inv_imb'] = fills['q_own'] - fills['q_opp']
fills['sum_ask'] = fills['up_ask'] + fills['dn_ask']

print("\n=== Q2 SIDE DECISION ===")
print("  more_own by leg:", fills.groupby('leg')['side_up'].mean().to_dict())
print("  relative_cheap overall:", round(fills['relative_cheap'].mean(), 3))
print("  relative_cheap by leg:", fills.groupby('leg')['relative_cheap'].mean().to_dict())
print("  buys_matching_oracle (bret5 dir):",
      round(((fills['side_up'] == 1) == (fills['bret5'] > 0)).mean(), 3))
print("  buys_matching_rtds (rtds5 dir):",
      round(((fills['side_up'] == 1) == (fills['rtds_ret5'] > 0)).mean(), 3))

hedge = fills[fills['leg'] == 'hedge']
rebal = fills[fills['leg'] == 'rebal']
print(f"  hedge: buys Up when bret5>0 = {hedge[hedge['bret5']>0]['side_up'].mean():.3f}, bret5<0 = {hedge[hedge['bret5']<0]['side_up'].mean():.3f}")

# ============================================================
# Q3: Maker vs taker split
# ============================================================
print("\n=== Q3 MAKER/TAKER ===")
for lname, g in fills.groupby('leg'):
    print(f"  {lname}: n={len(g)}, at_ask={g['at_ask'].mean():.3f}, at_bid={g['at_bid'].mean():.3f}, price={g['price'].mean():.3f}, off={g['off'].mean():.0f}s")
print(f"  Overall: at_ask={fills['at_ask'].mean():.3f}, at_bid={fills['at_bid'].mean():.3f}")
print()
# Taker rate by imbalance quartile
fills['imb_q'] = pd.qcut(fills['inv_imb'].abs(), 4, labels=['q1', 'q2', 'q3', 'q4'])
print("  at_ask by |imbalance| quartile:",
      fills.groupby('imb_q', observed=True)['at_ask'].mean().to_dict())

# ============================================================
# Q4: Timing of second side
# ============================================================
ft_s = ft.sort_values(['slug', 'ts_dt'])
first_side = ft_s.groupby(['slug', 'outcome'])['ts_dt'].min().unstack()
first_side.columns = ['first_dn', 'first_up']
both_timing = first_side.dropna().copy()
both_timing['slot_s'] = both_timing.index.map(lambda s: int(s.split('-')[-1]))
both_timing['slot_dt'] = pd.to_datetime(both_timing['slot_s'], unit='s', utc=True)
both_timing['first_up_off'] = (both_timing['first_up'] - both_timing['slot_dt']).dt.total_seconds()
both_timing['first_dn_off'] = (both_timing['first_dn'] - both_timing['slot_dt']).dt.total_seconds()
both_timing['lag'] = (both_timing['first_up_off'] - both_timing['first_dn_off']).abs()
both_timing['which_first'] = np.where(
    both_timing['first_up_off'] < both_timing['first_dn_off'], 'Up', 'Down')

print("\n=== Q4 TIMING OF SECOND SIDE ===")
print(f"  which_first: {both_timing['which_first'].value_counts().to_dict()}")
print(f"  lag median: {both_timing['lag'].median():.0f}s, mean: {both_timing['lag'].mean():.1f}s")
for threshold in [30, 60, 120, 300]:
    print(f"  lag<{threshold}s: {(both_timing['lag'] < threshold).mean():.3f}")
print(f"  first side offset median: up={both_timing['first_up_off'].median():.0f}s, dn={both_timing['first_dn_off'].median():.0f}s")

# ============================================================
# Q5: Rebate
# ============================================================
rebates = json.load(open(f'{CACHE}/../_pm_portfolio/0xb945945d/activity_MAKER_REBATE.json'))
total_rebate = sum(r['usdcSize'] for r in rebates)
print(f"\n=== REBATE: {total_rebate:.1f} total, {len(rebates)} events ===")

print("\nDONE")
