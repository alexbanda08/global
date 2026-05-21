"""Compare v1 vs v2 fire timing for eth_5m to test 'v2 fires later' hypothesis.

For each slug where both v1 and v2 fired (any policy), look at:
- fire timestamp delta (v2_ts - v1_ts)
- entry price delta
"""
import pandas as pd, json
from pathlib import Path

# Resolutions
df = pd.read_csv('strategy_lab/monitoring/_logs/vps3/momo_resolutions_36h.csv')
rows = []
for _, r in df.iterrows():
    try:
        d = json.loads(r['data'])
    except Exception:
        continue
    d['sleeve_id'] = r['sleeve_id']
    d['ts'] = r['at']
    rows.append(d)
ev = pd.DataFrame(rows)
ev['ts'] = pd.to_datetime(ev['ts'], utc=True)
ev['entry_price'] = pd.to_numeric(ev['entry_price'], errors='coerce')
ev['pnl_usd'] = pd.to_numeric(ev['pnl_usd'], errors='coerce')
ev['is_f7'] = ev['sleeve_id'].str.endswith('_f7')
ev['cell'] = ev['sleeve_id'].str.replace('poly_updown_', '').str.replace('_f7', '')

F7_START = pd.Timestamp('2026-05-20 19:57', tz='UTC')
post = ev[ev['ts'] >= F7_START].copy()
e5 = post[post['cell'].str.startswith('eth_5m_') & post['is_f7']].copy()
e5['version'] = e5['cell'].apply(lambda c: 'v2' if 'v2' in c else 'v1')

# Per slug (condition_id), take the FIRST fire from each version
if 'condition_id' not in e5.columns:
    print('no condition_id col'); raise SystemExit
firsts = e5.sort_values('ts').groupby(['condition_id','version']).first().reset_index()
# Build paired set (slugs that had BOTH v1 and v2 fire)
piv = firsts.pivot_table(index='condition_id',
                         columns='version',
                         values=['ts','signal','entry_price','pnl_usd','won'],
                         aggfunc='first')
print('=== Slug-level pairing ===')
print(f'total unique slugs with eth_5m+F7 fires: {firsts.condition_id.nunique()}')
print(f'  v1 only:   { (firsts.groupby("condition_id").size()==1).sum() - (firsts.groupby("condition_id")["version"].apply(lambda s: "v2" in s.values).sum()) }')
v1_set = set(firsts[firsts.version=="v1"].condition_id)
v2_set = set(firsts[firsts.version=="v2"].condition_id)
both = v1_set & v2_set
only_v1 = v1_set - v2_set
only_v2 = v2_set - v1_set
print(f'  v1 only:   {len(only_v1)}')
print(f'  v2 only:   {len(only_v2)}')
print(f'  both:      {len(both)}')
print()

# For 'both' slugs, compute timing + entry deltas
paired = []
for cid in both:
    v1r = firsts[(firsts.condition_id==cid) & (firsts.version=='v1')].iloc[0]
    v2r = firsts[(firsts.condition_id==cid) & (firsts.version=='v2')].iloc[0]
    paired.append({
        'cid': cid[:10] + '..',
        'v1_ts': v1r['ts'], 'v2_ts': v2r['ts'],
        'dt_s': (v2r['ts'] - v1r['ts']).total_seconds(),
        'v1_signal': v1r['signal'], 'v2_signal': v2r['signal'],
        'sig_match': v1r['signal'] == v2r['signal'],
        'v1_entry': v1r['entry_price'], 'v2_entry': v2r['entry_price'],
        'dprice': v2r['entry_price'] - v1r['entry_price'],
        'v1_won': v1r['won'], 'v2_won': v2r['won'],
        'v1_pnl': v1r['pnl_usd'], 'v2_pnl': v2r['pnl_usd'],
    })
pdf = pd.DataFrame(paired).sort_values('v1_ts')
print('=== Paired slugs (v1 AND v2 fired) ===')
print(pdf.to_string(index=False))
print()
print(f'mean dt_s (v2 fires later by): {pdf["dt_s"].mean():.1f}s')
print(f'mean dprice (v2 entry - v1 entry): {pdf["dprice"].mean():+.4f}')
print(f'v1 wr in paired set: {pdf.v1_won.mean()*100:.1f}%   v2 wr: {pdf.v2_won.mean()*100:.1f}%')
print(f'v1 pnl sum: ${pdf.v1_pnl.sum():.2f}   v2 pnl sum: ${pdf.v2_pnl.sum():.2f}')
print()

print('=== Slugs where ONLY v2 fired (and lost most money) ===')
v2_only_df = firsts[firsts.condition_id.isin(only_v2)].sort_values('ts')
print(f'n={len(v2_only_df)} rows on {len(only_v2)} unique slugs')
agg = v2_only_df.groupby('signal').agg(
    n=('won','size'), wr=('won','mean'), pnl=('pnl_usd','sum')).round(3)
print(agg.to_string())

print()
print('=== Slugs where ONLY v1 fired (the winning ones v2 missed) ===')
v1_only_df = firsts[firsts.condition_id.isin(only_v1)].sort_values('ts')
print(f'n={len(v1_only_df)} rows on {len(only_v1)} unique slugs')
agg = v1_only_df.groupby('signal').agg(
    n=('won','size'), wr=('won','mean'), pnl=('pnl_usd','sum')).round(3)
print(agg.to_string())
