import os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pyarrow.parquet as pq
import pyarrow.compute as pc
import numpy as np
import pandas as pd

# ---- load resolutions ----
res = pq.read_table(r"data/v4/canonical/resolutions_hf.parquet").to_pandas()
res['start_s'] = (res['slot_start_us']//1_000_000).astype('int64')
res['end_s']   = (res['slot_end_us']//1_000_000).astype('int64')

COINS = ['BTC','ETH','SOL']  # binance 1s avail Jan->Jun for these
SYM = {c: f"BINANCE_SPOT_{c}_USDT" for c in COINS}

# window bounds to filter klines load
# bmoney: Jan2->Mar24 ; aliplayer: Apr6->21. Just load full range needed per coin from min/max of res for that coin (+ margin)
OFFSETS = [-150,-120,-90,-80,-74,-60,-30,0,30,60,74,80,90,120,150]

# build per-coin close lookup as dict second->close (1Hz). Load only relevant coins.
close_map = {}
pf = pq.ParquetFile(r"data/v4/canonical/klines_1s.parquet")
want_syms = set(SYM.values())
# determine global second range needed (with margin for offsets)
need_lo = int(res['start_s'].min()) - 400
need_hi = int(res['end_s'].max()) + 400
for c in COINS:
    close_map[c] = {}
for rg in range(pf.num_row_groups):
    tbl = pf.read_row_group(rg, columns=['symbol_id','period_id','time_period_start_us','price_close'])
    si = tbl.column('symbol_id').to_pylist()
    # quick skip if no wanted sym in this rg
    # filter
    df = tbl.to_pandas()
    df = df[df['symbol_id'].isin(want_syms) & (df['period_id']=='1SEC')]
    if len(df)==0: continue
    df['s'] = (df['time_period_start_us']//1_000_000).astype('int64')
    df = df[(df['s']>=need_lo)&(df['s']<=need_hi)]
    if len(df)==0: continue
    for c in COINS:
        sub = df[df['symbol_id']==SYM[c]]
        if len(sub):
            close_map[c].update(dict(zip(sub['s'].values, sub['price_close'].values)))

for c in COINS:
    print(f"{c}: {len(close_map[c])} 1s closes loaded, range {min(close_map[c]) if close_map[c] else None}..{max(close_map[c]) if close_map[c] else None}")

# restrict resolutions to coins we have klines for, and to 5m/15m
work = res[res['ticker'].isin(COINS) & res['timeframe'].isin(['5m','15m'])].copy()
print("work rows:", len(work), work.groupby(['source','timeframe']).size().to_dict())

def implied(c, s_start, s_end):
    cm = close_map[c]
    p0 = cm.get(s_start); p1 = cm.get(s_end)
    if p0 is None or p1 is None:
        return None, None
    return p0, p1

rows = []
grp = work.groupby(['source','timeframe'])
for (src,tf), g in grp:
    n = len(g)
    arr_start = g['start_s'].values
    arr_end = g['end_s'].values
    coins = g['ticker'].values
    out = g['outcome'].values  # 'Up'/'Down'
    for off in OFFSETS:
        agree=0; valid=0; flat=0
        for i in range(n):
            c = coins[i]
            ss = int(arr_start[i])+off
            se = int(arr_end[i])+off
            p0,p1 = implied(c, ss, se)
            if p0 is None: continue
            valid+=1
            if p1>p0: imp='Up'
            elif p1<p0: imp='Down'
            else:
                flat+=1; imp='flat'
            if imp==out[i]: agree+=1
        rows.append(dict(source=src,tf=tf,offset=off,n=n,valid=valid,
                         agree=agree, agree_pct=(agree/valid*100 if valid else 0), flat=flat))

rep = pd.DataFrame(rows)
pd.set_option('display.width',200); pd.set_option('display.max_rows',300)
print(rep.to_string(index=False))

# argmax per group
print("\n=== ARGMAX offset per (source,tf) ===")
for (src,tf), g in rep.groupby(['source','tf']):
    best = g.loc[g['agree_pct'].idxmax()]
    print(f"{src:18s} {tf:4s} -> offset={int(best['offset']):+4d}s  agree={best['agree_pct']:.1f}%  (off0={g[g.offset==0]['agree_pct'].values[0]:.1f}%)")

rep.to_csv(r"_sweep_offset_result.csv", index=False)
print("\nsaved _sweep_offset_result.csv")
