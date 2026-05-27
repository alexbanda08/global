"""Re-project V6 and V7 tables to FULL 32.7d window instead of legacy 28d."""
import pandas as pd
import os

base = 'strategy_lab/sniper_search_2026_05_27'

# Real data spans (v3 fires) per CLAUDE.md
FULL_DAYS = 32.66       # Apr 24 → May 26 17:25 UTC
LOCKBOX_DAYS = 4.0      # standard 4d holdout

def project(dpt_lb, n_lb, days_lb=LOCKBOX_DAYS, target_days=FULL_DAYS):
    """Project lockbox dpt × rate × target_days."""
    if pd.isna(dpt_lb) or pd.isna(n_lb): return float('nan')
    try:
        return float(dpt_lb) * (float(n_lb) / days_lb) * target_days
    except:
        return float('nan')

def project_annual(dpt_lb, n_lb, days_lb=LOCKBOX_DAYS):
    return project(dpt_lb, n_lb, days_lb, 365.25)

def fmt_dollar(x):
    if pd.isna(x): return 'NA'
    try: return f'${float(x):+,.0f}'
    except: return 'NA'

print(f'Projection base: FULL window = {FULL_DAYS:.2f}d (lockbox = {LOCKBOX_DAYS}d)\n')

# ========== V6 ==========
v6 = pd.read_csv(f'{base}/_v6_full_table.csv')
print(f'### V6 sleeves (30 total)\n')

# Need dpt_lb and n_lb columns from raw stripped strings
def parse_dollar(s):
    if pd.isna(s): return float('nan')
    try:
        v = str(s).replace('$', '').replace('+', '').replace(',', '').strip()
        return float(v)
    except: return float('nan')

def parse_num(s):
    if pd.isna(s) or str(s) == 'NA': return float('nan')
    try: return float(str(s).replace(',', ''))
    except: return float('nan')

# V6 dpt_lb column is dollar-formatted
v6['_dpt_lb'] = v6['dpt_lb'].apply(parse_dollar)
v6['_n_lb']   = v6['n_lb'].apply(parse_num)
v6['proj_full_33d'] = v6.apply(lambda r: project(r._dpt_lb, r._n_lb), axis=1)
v6['proj_annual']   = v6.apply(lambda r: project_annual(r._dpt_lb, r._n_lb), axis=1)

print(f'{"market":10} {"#":>3} {"sleeve":40} {"n_lb":>5} {"$/tr_lb":>9} {"32.7d proj":>13} {"annual":>13}')
for _, r in v6.iterrows():
    sid = str(r.sleeve_id)[:38]
    print(f'{r.market:10} {int(r["rank"]):3d} {sid:40} {str(r.n_lb):>5} {str(r.dpt_lb):>9} {fmt_dollar(r.proj_full_33d):>13} {fmt_dollar(r.proj_annual):>13}')

v6.to_csv(f'{base}/_v6_full_table_REPROJECTED.csv', index=False)
print(f'\nSaved: {base}/_v6_full_table_REPROJECTED.csv\n')

# ========== V7 ==========
v7 = pd.read_csv(f'{base}/_v7_full_table.csv')
print(f'\n### V7 sleeves (29 total)\n')

# V7 has dpt_lb as raw float
v7['_dpt_lb'] = v7['dpt_lb'].apply(lambda x: parse_num(x))
v7['_n_lb']   = v7['n_lb'].apply(parse_num)
v7['proj_full_33d'] = v7.apply(lambda r: project(r._dpt_lb, r._n_lb), axis=1)
v7['proj_annual']   = v7.apply(lambda r: project_annual(r._dpt_lb, r._n_lb), axis=1)

print(f'{"market":10} {"#":>3} {"sleeve":40} {"n_lb":>5} {"$/tr_lb":>9} {"32.7d proj":>13} {"annual":>13}')
for _, r in v7.iterrows():
    sid = str(r.sleeve_id)[:38]
    dpt_str = f'${float(r._dpt_lb):+.2f}' if pd.notna(r._dpt_lb) else 'NA'
    print(f'{r.market:10} {int(r["rank"]):3d} {sid:40} {str(int(r._n_lb)) if pd.notna(r._n_lb) else "NA":>5} {dpt_str:>9} {fmt_dollar(r.proj_full_33d):>13} {fmt_dollar(r.proj_annual):>13}')

v7.to_csv(f'{base}/_v7_full_table_REPROJECTED.csv', index=False)
print(f'\nSaved: {base}/_v7_full_table_REPROJECTED.csv')

# ========== Aggregate roster per best-per-market ==========
print(f'\n\n### Best-per-market aggregate (32.7d + annual projections)\n')
print(f'{"version":7} {"market":10} {"sleeve":40} {"$/tr_lb":>9} {"n_lb":>5} {"32.7d":>13} {"annual":>13}')

best_picks = [
    ('V6 sel', 'BTC 5m',  v6[v6.market=='BTC 5m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V6 sel', 'ETH 5m',  v6[v6.market=='ETH 5m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V6 sel', 'SOL 5m',  v6[v6.market=='SOL 5m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V6 sel', 'BTC 15m', v6[v6.market=='BTC 15m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V6 sel', 'ETH 15m', v6[v6.market=='ETH 15m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V6 sel', 'SOL 15m', v6[v6.market=='SOL 15m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V7',     'BTC 5m',  v7[v7.market=='BTC 5m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V7',     'ETH 5m',  v7[v7.market=='ETH 5m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V7',     'SOL 5m',  v7[v7.market=='SOL 5m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V7',     'BTC 15m', v7[v7.market=='BTC 15m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V7',     'ETH 15m', v7[v7.market=='ETH 15m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
    ('V7',     'SOL 15m', v7[v7.market=='SOL 15m'].sort_values('_dpt_lb', ascending=False).iloc[0]),
]

for ver, mkt, r in best_picks:
    sid = str(r.sleeve_id)[:38]
    dpt = float(r._dpt_lb) if pd.notna(r._dpt_lb) else 0
    print(f'{ver:7} {mkt:10} {sid:40} ${dpt:+7.2f} {str(int(r._n_lb)) if pd.notna(r._n_lb) else "NA":>5} {fmt_dollar(r.proj_full_33d):>13} {fmt_dollar(r.proj_annual):>13}')

# Sum of best-per-market V7 projections (pre-dedup)
v7_total_33d = sum(float(r.proj_full_33d) if pd.notna(r.proj_full_33d) else 0
                   for _, _, r in best_picks if _[0] == 'V7' or True)  # all
v6_picks = [r for v, _, r in best_picks if v == 'V6 sel']
v7_picks = [r for v, _, r in best_picks if v == 'V7']

v6_total_33d = sum(r.proj_full_33d if pd.notna(r.proj_full_33d) else 0 for r in v6_picks)
v7_total_33d = sum(r.proj_full_33d if pd.notna(r.proj_full_33d) else 0 for r in v7_picks)
v6_total_yr  = sum(r.proj_annual   if pd.notna(r.proj_annual)   else 0 for r in v6_picks)
v7_total_yr  = sum(r.proj_annual   if pd.notna(r.proj_annual)   else 0 for r in v7_picks)

print(f'\n--- Combined sums (pre-overlap-dedup) ---')
print(f'V6 best-per-market total: 33d {fmt_dollar(v6_total_33d)}   annual {fmt_dollar(v6_total_yr)}')
print(f'V7 best-per-market total: 33d {fmt_dollar(v7_total_33d)}   annual {fmt_dollar(v7_total_yr)}')
