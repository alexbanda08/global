"""Decode the strategy of 0xf69af0b9 (BTC-5m favorite hold-to-resolution bot)
from its Polymarket activity tape. No canonical microstructure needed."""
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt")
import pandas as pd, numpy as np
from polymarket_api import fetch_activity, activity_to_df

W="0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c"
act=fetch_activity(W, use_cache=True)
df=activity_to_df(act)
for c in ["size","price","usdcSize","timestamp","outcomeIndex"]:
    if c in df: df[c]=pd.to_numeric(df[c],errors="coerce")

tr=df[df["type"]=="TRADE"].copy()
tr["asset"]=tr["slug"].str.extract(r"^([a-z0-9]+)-updown")[0]
tr["tf"]=tr["slug"].str.extract(r"-updown-(\d+[mh])-")[0]
tr["slot_start"]=tr["slug"].str.rsplit("-",n=1).str[-1]
tr["slot_start"]=pd.to_numeric(tr["slot_start"],errors="coerce")
tr["entry_offset_s"]=tr["timestamp"]-tr["slot_start"]      # secs into the window
buys=tr[tr["side"].str.upper()=="BUY"].copy()

print(f"TOTAL trades={len(tr)}  buys={len(buys)}  sells={(tr['side'].str.upper()=='SELL').sum()}")
print(f"\n-- asset x tf mix (buys) --\n{buys.groupby(['asset','tf']).size().sort_values(ascending=False).head(12).to_string()}")
print(f"\n-- notional usdcSize --\n{buys['usdcSize'].describe(percentiles=[.1,.5,.9]).round(2).to_string()}")
print(f"\n-- entry price (buy) --\n{buys['price'].describe(percentiles=[.05,.25,.5,.75,.95]).round(3).to_string()}")
fav=(buys["price"]>0.5).mean()
print(f"\nbuys on FAVORITE side (price>0.5): {fav*100:.1f}%  | underdog(<0.5): {(buys['price']<0.5).mean()*100:.1f}%")
print(f"entry within window (entry_offset_s) percentiles:")
print(buys["entry_offset_s"].describe(percentiles=[.05,.25,.5,.75,.95]).round(1).to_string())

# WR from redeems: REDEEM rows have usdcSize>0 = payout; match by conditionId
rd=df[df["type"]=="REDEEM"].copy()
print(f"\nredeem rows={len(rd)}  redeem total $={pd.to_numeric(rd['usdcSize'],errors='coerce').sum():.2f}")
# per-trade win: a buy WON if its conditionId got a positive redeem
won_cids=set(rd.loc[pd.to_numeric(rd['usdcSize'],errors='coerce')>0,"conditionId"])
buys["won"]=buys["conditionId"].isin(won_cids)
print(f"approx WR (buys whose market redeemed >0): {buys['won'].mean()*100:.1f}%  n={len(buys)}")

# cadence: trades/day, consecutive-slot rate
buys["day"]=pd.to_datetime(buys["timestamp"],unit="s").dt.date
print(f"\n-- buys per day (last 10) --\n{buys.groupby('day').size().tail(10).to_string()}")
print(f"active days={buys['day'].nunique()}  span={buys['timestamp'].min()}->{buys['timestamp'].max()}")
# does it fire EVERY consecutive 5m btc slot? gap between consecutive btc-5m slots
b5=buys[(buys['asset']=='btc')&(buys['tf']=='5m')].sort_values('slot_start')
gaps=b5['slot_start'].diff().dropna()
print(f"\nbtc-5m buys={len(b5)}  consecutive-300s-gap rate={ (gaps==300).mean()*100:.0f}%  gap dist:{gaps.value_counts().head(5).to_dict()}")

# side vs implied: how often does it pick the side that ends up winning at entry favorite
print(f"\n-- side outcome mix --\n{buys['outcome'].value_counts().to_dict()}")
buys[["timestamp","asset","tf","outcome","price","size","usdcSize","entry_offset_s","won","slug"]].tail(40).to_csv(
    r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\_f69_recent_buys.csv",index=False)
print("\nsaved recent buys -> cache/_f69_recent_buys.csv")
