"""Diagnose eth_5m_momo_v2 + F7 regression vs v1.

Compares F7-passed fires on eth 5m between v1 (works) and v2 (collapsed to ~7% WR).
"""
import pandas as pd, json

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
for c in ('pnl_usd','entry_price','strike_price','settlement_price'):
    ev[c] = pd.to_numeric(ev[c], errors='coerce')
ev['ts'] = pd.to_datetime(ev['ts'], utc=True)
ev['is_f7'] = ev['sleeve_id'].str.endswith('_f7')
ev['cell'] = ev['sleeve_id'].str.replace('poly_updown_', '').str.replace('_f7', '')

F7_START = pd.Timestamp('2026-05-20 19:57', tz='UTC')
post = ev[ev['ts'] >= F7_START].copy()

e5 = post[post['cell'].str.startswith('eth_5m_')].copy()
e5['version'] = e5['cell'].apply(lambda c: 'v2' if 'v2' in c else 'v1')
e5['policy']  = e5['cell'].str.split('_').str[-1]

e5_f7 = e5[e5['is_f7']].copy()
print('=== eth_5m + F7 events (post-deploy) ===')
n_v1 = (e5_f7.version == 'v1').sum()
n_v2 = (e5_f7.version == 'v2').sum()
print(f'n={len(e5_f7)}  (v1={n_v1}, v2={n_v2})')
print()

e5_f7['move_pct'] = (e5_f7['settlement_price'] - e5_f7['strike_price']) / e5_f7['strike_price'] * 100
e5_f7['signed_move_pct'] = e5_f7.apply(
    lambda r: r['move_pct'] * (1 if r['signal'] == 'UP' else -1), axis=1)
e5_f7['entry_dist_pct'] = (e5_f7['entry_price'] - e5_f7['strike_price']) / e5_f7['strike_price'] * 100

for ver in ('v1', 'v2'):
    s = e5_f7[e5_f7['version'] == ver]
    if len(s) == 0:
        continue
    wr = s['won'].mean() * 100
    avg = s['pnl_usd'].mean()
    print(f'--- {ver} (n={len(s)}, wr={wr:.1f}%, avg_pnl=${avg:.2f}) ---')
    up = (s.signal == 'UP').sum()
    dn = (s.signal == 'DOWN').sum()
    print(f'  signal mix: UP={up}/{len(s)}  DOWN={dn}/{len(s)}')
    print(f'  signed_move_pct (in favor of bet):  mean={s.signed_move_pct.mean():+.3f}%  median={s.signed_move_pct.median():+.3f}%')
    print(f'    win rows: mean={s[s.won].signed_move_pct.mean():+.3f}%')
    print(f'    los rows: mean={s[~s.won].signed_move_pct.mean():+.3f}%')
    print(f'  entry_dist_from_strike_pct: mean={s.entry_dist_pct.mean():+.3f}%  median={s.entry_dist_pct.median():+.3f}%')
    print(f'    (positive = entry above strike at fire time)')
    print(f'  entry_price stats: min={s.entry_price.min():.3f}  median={s.entry_price.median():.3f}  max={s.entry_price.max():.3f}')
    print()

print('=== eth_5m_v2 + F7 fires (worst cohort) — unique fires ===')
v2 = e5_f7[e5_f7.version == 'v2'].sort_values('ts')
cols = ['ts','policy','signal','strike_price','entry_price','settlement_price',
        'signed_move_pct','entry_dist_pct','won','pnl_usd','hedged']
v2_unique = v2.drop_duplicates(subset=['ts','signal','strike_price'], keep='first')[cols]
print(v2_unique.to_string(index=False))
print()

print('=== eth_5m_v1 + F7 fires (works) — unique fires ===')
v1 = e5_f7[e5_f7.version == 'v1'].sort_values('ts')
v1_unique = v1.drop_duplicates(subset=['ts','signal','strike_price'], keep='first')[cols]
print(v1_unique.to_string(index=False))
