"""One-off analysis for 0xd44e2993 — indirect via takers' trades_chain.
Reads _d44e2993_indirect.parquet (already extracted) and prints all stats.
"""
import pandas as pd
import numpy as np

trades = pd.read_parquet('strategy_lab/wallet_hunt/cache/_d44e2993_indirect.parquet')
tl = pd.read_parquet('strategy_lab/wallet_hunt/cache/_token_lookup.parquet')[
    ['asset_id','slug','outcome','market_class','mkt_asset']
]

trades['asset_str'] = trades['asset'].astype(str)
tl['asset_str'] = tl['asset_id'].astype(str)
m = trades.merge(tl, on='asset_str', how='left')

print('=== JOIN COVERAGE ===')
print(f'Total trades: {len(m)}')
print(f'With slug: {m["slug"].notna().sum()} ({m["slug"].notna().mean()*100:.1f}%)')

m['ts'] = pd.to_datetime(m['timestamp'], unit='s', utc=True)
print(f'Time span: {m["ts"].min()} -> {m["ts"].max()}')
span_days = (m['timestamp'].max()-m['timestamp'].min())/86400.0
print(f'Span days: {span_days:.2f}')

tot_usdc = m['usdc_notional'].sum()
print(f'Total USDC notional: ${tot_usdc:,.0f}')
print(f'Daily USDC (observed, lower bound): ${tot_usdc/span_days:,.0f}')

print()
print('=== MAKER CONFIRMATION ===')
print(f'maker==target rows: {(m["maker_l"]=="0xd44e29936409019f93993de8bd603ef6cb1bb15e").sum()}/{len(m)}')
print('side (taker side from our taker wallet perspective):')
print(m['side'].value_counts())
print('side_uint dist:')
print(m['side_uint'].value_counts())
print('observed via:')
print(m['observed_via'].value_counts())

ms = m[m['slug'].notna()].copy()
print()
print(f'=== PER-SLUG ({len(ms)} rows with slug) ===')
g = ms.groupby('slug').agg(
    fills=('size','count'),
    shares=('size','sum'),
    usdc=('usdc_notional','sum'),
    asset=('mkt_asset','first'),
    tf=('market_class','first'),
    t_min=('timestamp','min'),
    t_max=('timestamp','max'),
).reset_index()
g['dur_min'] = (g['t_max']-g['t_min'])/60.0
print(f'Unique slugs touched: {len(g)}')
print(f'Slugs/day: {len(g)/span_days:.1f}')
print(f'FILLS/SLUG  median={g["fills"].median():.1f}  p25={g["fills"].quantile(.25):.1f}  p75={g["fills"].quantile(.75):.1f}  mean={g["fills"].mean():.1f}  max={g["fills"].max()}')
print(f'SHARES/SLUG median={g["shares"].median():.1f}  p25={g["shares"].quantile(.25):.1f}  p75={g["shares"].quantile(.75):.1f}')
print(f'USDC/SLUG   median=${g["usdc"].median():.2f}  p25=${g["usdc"].quantile(.25):.2f}  p75=${g["usdc"].quantile(.75):.2f}  mean=${g["usdc"].mean():.2f}')
print(f'SIZE/FILL   median={ms["size"].median():.2f}  p25={ms["size"].quantile(.25):.2f}  p75={ms["size"].quantile(.75):.2f}  mean={ms["size"].mean():.2f}')
print(f'PRICE/FILL  median={ms["price"].median():.3f}  p25={ms["price"].quantile(.25):.3f}  p75={ms["price"].quantile(.75):.3f}')
print(f'DUR_MIN     median={g["dur_min"].median():.1f}  p25={g["dur_min"].quantile(.25):.1f}  p75={g["dur_min"].quantile(.75):.1f}')

print()
print('=== CELL FOCUS (mkt_asset x market_class) ===')
cells = ms.groupby(['mkt_asset','market_class']).agg(
    fills=('size','count'),
    usdc=('usdc_notional','sum'),
    slugs=('slug','nunique'),
).reset_index().sort_values('fills', ascending=False)
cells['pct_fills'] = cells['fills']/cells['fills'].sum()*100
cells['pct_usdc'] = cells['usdc']/cells['usdc'].sum()*100
print(cells.to_string(index=False))

print()
print('=== PER-CELL FILLS/SLUG & USDC/SLUG ===')
for (a,tf), grp in ms.groupby(['mkt_asset','market_class']):
    gg = grp.groupby('slug').agg(fills=('size','count'), usdc=('usdc_notional','sum'))
    if len(gg)<3: continue
    print(f'  {a}/{tf}: n_slugs={len(gg)}, median fills/slug={gg["fills"].median():.1f}, median $/slug=${gg["usdc"].median():.2f}, total_usdc=${gg["usdc"].sum():,.0f}')

print()
print('=== OUTCOME (which side they post) ===')
print(ms['outcome'].value_counts())

print()
print('=== ORPHANS ===')
orph = m[m['slug'].isna()]
print(f'orphan rows: {len(orph)} / {len(m)} ({len(orph)/len(m)*100:.1f}%)  usdc=${orph["usdc_notional"].sum():,.0f}')
if len(orph) > 0:
    print('sample orphan assets:')
    print(orph['asset_str'].value_counts().head(5))

print()
print('=== DAILY VOLUME PROFILE ===')
m['date'] = m['ts'].dt.date
daily = m.groupby('date').agg(fills=('size','count'), usdc=('usdc_notional','sum'), slugs=('asset_str','nunique')).reset_index()
print(daily.to_string(index=False))

# Hour-of-day
print()
print('=== HOUR-OF-DAY (UTC) ===')
m['hour'] = m['ts'].dt.hour
hod = m.groupby('hour').agg(fills=('size','count'), usdc=('usdc_notional','sum')).reset_index()
print(hod.to_string(index=False))
