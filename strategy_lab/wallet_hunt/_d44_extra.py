"""Extra checks for 0xd44e2993: split observed-via, two-sidedness, price distro by side."""
import pandas as pd
import numpy as np

trades = pd.read_parquet('strategy_lab/wallet_hunt/cache/_d44e2993_indirect.parquet')
tl = pd.read_parquet('strategy_lab/wallet_hunt/cache/_token_lookup.parquet')[
    ['asset_id','slug','outcome','market_class','mkt_asset']
]
trades['asset_str'] = trades['asset'].astype(str)
tl['asset_str'] = tl['asset_id'].astype(str)
m = trades.merge(tl, on='asset_str', how='left')
ms = m[m['slug'].notna()].copy()

# Two-sidedness: does d44 post BOTH Up AND Down within same slug?
slug_out = ms.groupby(['slug','outcome']).size().unstack(fill_value=0)
both = ((slug_out.get('Up',0)>0) & (slug_out.get('Down',0)>0)).sum()
only_up = ((slug_out.get('Up',0)>0) & (slug_out.get('Down',0)==0)).sum()
only_dn = ((slug_out.get('Up',0)==0) & (slug_out.get('Down',0)>0)).sum()
print(f'BOTH SIDES slugs:    {both}')
print(f'Only Up slugs:       {only_up}')
print(f'Only Down slugs:     {only_dn}')
print(f'Total slugs:         {len(slug_out)}')
print(f'Two-sided pct:       {both/len(slug_out)*100:.1f}%')

# Price distribution by outcome
print()
print('=== PRICE BY OUTCOME (where d44 posted) ===')
for out in ['Up','Down']:
    sub = ms[ms['outcome']==out]['price']
    if len(sub)==0: continue
    print(f'  {out}: n={len(sub)} median={sub.median():.3f} p25={sub.quantile(.25):.3f} p75={sub.quantile(.75):.3f} mean={sub.mean():.3f}')

# Mean fill notional
print()
print('=== USDC PER FILL ===')
nv = ms['usdc_notional']
print(f'  median=${nv.median():.2f}  p25=${nv.quantile(.25):.2f}  p75=${nv.quantile(.75):.2f}  mean=${nv.mean():.2f}')

# Slug start time vs first-fill: is d44 posting early or late?
ms['slug_start'] = ms['slug'].str.rsplit('-', n=1).str[-1].astype(int)
ms['secs_after_slot_start'] = ms['timestamp'] - ms['slug_start']
# updown_15m slot is 15min = 900s window
within = ms[(ms['secs_after_slot_start']>=-30) & (ms['secs_after_slot_start']<=1000)]
print()
print('=== FILL TIMING WITHIN SLUG (15m window) ===')
print(f'  n_within: {len(within)}/{len(ms)}')
print(f'  secs_after_slot_start: median={within["secs_after_slot_start"].median():.0f}  p25={within["secs_after_slot_start"].quantile(.25):.0f}  p75={within["secs_after_slot_start"].quantile(.75):.0f}')

# Compare to the 3 known mint-and-sell wallets
print()
print('=== KNOWN-WALLET BASELINES (recompute quickly from their own caches) ===')
from pathlib import Path
base = Path('strategy_lab/wallet_hunt/cache')
tl2 = tl
for w in ['0x89b5cdaa', '0x04b6d7e9', '0xeebde7a0']:
    p = base/w/'trades_chain.parquet'
    if not p.exists(): continue
    t = pd.read_parquet(p)
    t['asset_str'] = t['asset'].astype(str)
    j = t.merge(tl2[['asset_str','slug','mkt_asset','market_class']], on='asset_str', how='left')
    js = j[j['slug'].notna()]
    span = (j['timestamp'].max()-j['timestamp'].min())/86400.0
    gg = js.groupby('slug').agg(fills=('size','count'), usdc=('usdc_notional','sum'))
    cells = js.groupby(['mkt_asset','market_class']).size().to_dict()
    daily = j['usdc_notional'].sum()/span
    maker_pct = j['wallet_is_maker'].mean()*100 if 'wallet_is_maker' in j.columns else float('nan')
    print(f'{w}: n_trades={len(j)} span_d={span:.1f} maker%={maker_pct:.1f}  median fills/slug={gg["fills"].median():.0f}  median $/slug=${gg["usdc"].median():.2f}  daily=${daily:,.0f}  cells={cells}')
