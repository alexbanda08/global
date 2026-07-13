import pandas as pd, numpy as np, re

df = pd.read_csv('b945_trades_2026_07_13.csv')
print("rows:", len(df))
print("side counts:\n", df['side'].value_counts())

# parse slug -> coin, tf, slot_start
def parse_slug(s):
    m = re.match(r'([a-z]+)-updown-(\d+m)-(\d+)', str(s))
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    return None, None, None

parsed = df['slug'].apply(parse_slug)
df['coin'] = parsed.apply(lambda x: x[0])
df['tf'] = parsed.apply(lambda x: x[1])
df['slot_start'] = parsed.apply(lambda x: x[2])

print("\ncoin x tf counts:\n", df.groupby(['coin','tf']).size())

buys = df[df['side']=='BUY'].copy()
print(f"\nBUY rows: {len(buys)} / {len(df)} ({100*len(buys)/len(df):.1f}%)")

buys['notional'] = buys['price']*buys['size']
print("\nBUY notional by coin x tf:")
print(buys.groupby(['coin','tf'])['notional'].agg(['sum','count','mean']))

# fills per slug
fills_per_slug = buys.groupby('slug').size()
print("\nfills/slug mean:", fills_per_slug.mean(), "median:", fills_per_slug.median())

# clip size dist
print("\nclip $ (notional) dist:", buys['notional'].describe())

# entry timing within window: timestamp - slot_start
buys['sec_from_start'] = buys['timestamp'] - buys['slot_start']
print("\nentry timing sec_from_start (BUY): p10/50/90:",
      buys['sec_from_start'].quantile([0.1,0.5,0.9]).values)

# pair rate: % slugs with both Up and Down bought
pair_stats = buys.groupby('slug')['outcome'].apply(lambda x: set(x))
both = pair_stats.apply(lambda s: {'Up','Down'}.issubset(s))
print(f"\npair rate (both sides bought): {both.mean()*100:.1f}% of {len(pair_stats)} slugs")

# pair_frac: fraction of notional on the minority side per paired slug
def pair_frac(g):
    up = g[g['outcome']=='Up']['notional'].sum()
    dn = g[g['outcome']=='Down']['notional'].sum()
    tot = up+dn
    if tot==0: return np.nan
    return min(up,dn)/tot

pf = buys.groupby('slug').apply(pair_frac)
paired_slugs = pair_stats[both].index
print("pair_frac median (paired slugs only):", pf.loc[paired_slugs].median())

# pvs: avg up price + avg dn price on both-sided slugs
def pvs(g):
    up_px = np.average(g[g['outcome']=='Up']['price'], weights=g[g['outcome']=='Up']['size']) if (g['outcome']=='Up').any() else np.nan
    dn_px = np.average(g[g['outcome']=='Down']['price'], weights=g[g['outcome']=='Down']['size']) if (g['outcome']=='Down').any() else np.nan
    return up_px+dn_px

pvs_vals = buys.groupby('slug').apply(pvs)
print("pvs median (paired slugs):", pvs_vals.loc[paired_slugs].median())

# % sells
print(f"\n%sells: {100*(df['side']=='SELL').mean():.2f}%")

# save summary
summary = {
    'total_rows': len(df),
    'buy_rows': len(buys),
    'pct_sells': float((df['side']=='SELL').mean()*100),
    'n_slugs': int(buys['slug'].nunique()),
    'fills_per_slug_mean': float(fills_per_slug.mean()),
    'fills_per_slug_median': float(fills_per_slug.median()),
    'clip_notional_median': float(buys['notional'].median()),
    'clip_notional_mean': float(buys['notional'].mean()),
    'timing_p10': float(buys['sec_from_start'].quantile(0.1)),
    'timing_p50': float(buys['sec_from_start'].quantile(0.5)),
    'timing_p90': float(buys['sec_from_start'].quantile(0.9)),
    'pair_rate_pct': float(both.mean()*100),
    'pair_frac_median': float(pf.loc[paired_slugs].median()),
    'pvs_median': float(pvs_vals.loc[paired_slugs].median()),
}
import json
with open('b945_signature_summary_2026_07_13.json','w') as f:
    json.dump(summary, f, indent=2)
print("\nsaved b945_signature_summary_2026_07_13.json")
print(json.dumps(summary, indent=2))

buys.to_csv('b945_buys_parsed_2026_07_13.csv', index=False)
print("saved b945_buys_parsed_2026_07_13.csv")
