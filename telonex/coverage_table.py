"""Full per-coin coverage matrix across production canonical + HF backfill. Uses parquet
metadata stats (fast) for periods on the billion-row BBO files."""
import pandas as pd, pyarrow.parquet as pq
from pathlib import Path
C=Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
BBO=Path(r"D:\global_data\canonical_bbo"); BBOT=Path(r"D:\global_data\canonical_bbo_trades")
def ts(us): return pd.to_datetime(int(us),unit="us",utc=True).strftime("%Y-%m-%d") if us is not None else "-"

def pq_period(path, tscol="timestamp_us"):
    """min/max of a ts column via row-group statistics (no full read), + num_rows."""
    pf=pq.ParquetFile(str(path)); md=pf.metadata
    names=[md.schema.column(i).name for i in range(md.num_columns)]
    if tscol not in names: return md.num_rows, None, None
    j=names.index(tscol); mn=None; mx=None
    for rg in range(md.num_row_groups):
        st=md.row_group(rg).column(j).statistics
        if st is None or not st.has_min_max: continue
        mn=st.min if mn is None else min(mn,st.min); mx=st.max if mx is None else max(mx,st.max)
    return md.num_rows, mn, mx

COINS=["btc","eth","sol","xrp","bnb","doge","hype"]
# (label, dir/file pattern, tscol, ticker-filter-or-None)
def check(coin):
    rows=[]
    # production L25 (btc/eth/sol only)
    p=C/"orderbook_l25"/f"{coin}.parquet"
    if p.exists():
        n,mn,mx=pq_period(p); rows.append(("L25 full-depth 10Hz (PROD/VPS3)", n, mn, mx))
    # HF backfill L25
    p=C/"orderbook_l25_backfill"/f"{coin}.parquet"
    if p.exists():
        n,mn,mx=pq_period(p); rows.append(("L25 full-depth 10Hz (HF backfill)", n, mn, mx))
    # BBO
    p=BBO/f"{coin}.parquet"
    if p.exists():
        n,mn,mx=pq_period(p); rows.append(("BBO top-of-book ~200Hz (HF)", n, mn, mx))
    # production trades
    p=C/"trades_polymarket"/f"{coin}.parquet"
    if p.exists():
        n,mn,mx=pq_period(p); rows.append(("trades (PROD/VPS3)", n, mn, mx))
    # HF trades (trentmkelly btc/eth)
    p=C/"trades_polymarket_hf"/f"{coin}.parquet"
    if p.exists():
        n,mn,mx=pq_period(p); rows.append(("trades (HF trentmkelly)", n, mn, mx))
    # BBO trades (aliplayer)
    p=BBOT/f"{coin}.parquet"
    if p.exists():
        n,mn,mx=pq_period(p); rows.append(("trades (HF aliplayer ticks)", n, mn, mx))
    return rows

# resolutions (by ticker, both sources)
res_prod=pd.read_parquet(C/"resolutions_from_rtds.parquet", columns=["ticker","slot_start_us"])
res_hf=pd.read_parquet(C/"resolutions_hf.parquet", columns=["ticker","slot_start_us"])
def res_for(coin):
    out=[]
    t=coin.upper()
    a=res_prod[res_prod.ticker==t]
    if len(a): out.append(("resolutions REAL/chainlink (PROD)", len(a), a.slot_start_us.min(), a.slot_start_us.max()))
    b=res_hf[res_hf.ticker==t]
    if len(b): out.append(("resolutions REAL (HF)", len(b), b.slot_start_us.min(), b.slot_start_us.max()))
    return out

print(f"{'COIN':<6}{'DATA TYPE':<38}{'ROWS':>14}  {'FROM':<12}{'TO':<12}")
print("-"*92)
for coin in COINS:
    blocks=check(coin)+res_for(coin)
    if not blocks:
        print(f"{coin.upper():<6}(no data)"); continue
    for i,(lbl,n,mn,mx) in enumerate(blocks):
        c=coin.upper() if i==0 else ""
        print(f"{c:<6}{lbl:<38}{n:>14,}  {ts(mn):<12}{ts(mx):<12}")
    print()
