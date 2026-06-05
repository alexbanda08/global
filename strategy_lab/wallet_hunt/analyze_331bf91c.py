"""Full trade-history analysis of 0x331bf91c (weather market trader).
Builds per-market table, category/time breakdown, copy-trade verdict."""
import sys, re
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt")
import pandas as pd, numpy as np, datetime
from polymarket_api import fetch_activity, activity_to_df

W="0x331bf91c132af9d921e1908ca0979363fc47193f"
OUT=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache"
df=activity_to_df(fetch_activity(W,use_cache=True))
for c in ["usdcSize","size","price","timestamp"]:
    if c in df: df[c]=pd.to_numeric(df[c],errors="coerce")
df["dt"]=pd.to_datetime(df["timestamp"],unit="s")
df["title"]=df["title"].astype(str)

# ---- category by title keyword ----
def cat(t):
    t=t.lower()
    if re.search(r"temperature|°|degrees|warmest|coldest|hottest|high temp|weather|rain|snow|precip|climate",t): return "weather"
    if re.search(r"up or down|bitcoin|ethereum|solana|btc|eth|sol",t): return "crypto-updown"
    return "other"
df["cat"]=df["title"].map(cat)

trade=df[df["type"]=="TRADE"].copy()
print(f"=== 0x331bf91c — activity {len(df)} rows | TRADE {len(trade)} REDEEM {(df['type']=='REDEEM').sum()} ===")
print(f"date span: {df['dt'].min()} -> {df['dt'].max()}")

# ---- cash PnL per conditionId (market) ----
# buys: -usdcSize ; sells: +usdcSize ; REDEEM/REWARD/REFERRAL/MAKER_REBATE: +usdcSize ; MERGE/SPLIT: ~0 cash
g=[]
for cid,sub in df.groupby("conditionId"):
    title=sub["title"].iloc[0]; c=cat(title)
    buys=sub[(sub["type"]=="TRADE")&(sub["side"].str.upper()=="BUY")]
    sells=sub[(sub["type"]=="TRADE")&(sub["side"].str.upper()=="SELL")]
    redeem=sub[sub["type"].isin(["REDEEM","REWARD","REFERRAL_REWARD","MAKER_REBATE"])]
    cost=buys["usdcSize"].sum()
    proceeds=sells["usdcSize"].sum()+redeem["usdcSize"].sum()
    net=proceeds-cost
    g.append({"conditionId":cid,"title":title[:70],"cat":c,
              "n_buys":len(buys),"n_sells":len(sells),"cost":round(cost,2),
              "proceeds":round(proceeds,2),"net":round(net,2),
              "first":sub["dt"].min(),"last":sub["dt"].max(),
              "won":1 if net>0 else 0})
mk=pd.DataFrame(g).sort_values("net",ascending=False)
mk.to_csv(OUT+r"\_331_per_market.csv",index=False)

print(f"\n=== PER-MARKET cash PnL (realized, n_markets={len(mk)}) ===")
print(f"total realized net = ${mk['net'].sum():,.2f}   (lb_profit_all=$65,203 incl open positions)")
print(f"market WR (net>0) = {mk['won'].mean()*100:.1f}%   avg net/market = ${mk['net'].mean():.2f}")

print(f"\n=== BY CATEGORY ===")
bc=mk.groupby("cat").agg(n_markets=("net","size"),cost=("cost","sum"),net=("net","sum"),
                         wr=("won","mean")).round(2)
bc["wr"]=(bc["wr"]*100).round(1); bc["net"]=bc["net"].round(0)
print(bc.sort_values("net",ascending=False).to_string())

print(f"\n=== MONTHLY realized PnL / volume / WR ===")
mk["ym"]=mk["last"].dt.to_period("M")
mo=mk.groupby("ym").agg(n_mkts=("net","size"),cost=("cost","sum"),net=("net","sum"),wr=("won","mean")).round(0)
mo["wr"]=(mk.groupby("ym")["won"].mean()*100).round(1)
print(mo.to_string())

print(f"\n=== TOP 12 markets by net ===")
print(mk.head(12)[["title","cat","cost","net","last"]].to_string(index=False))
print(f"\n=== WORST 8 markets by net ===")
print(mk.tail(8)[["title","cat","cost","net","last"]].to_string(index=False))

# trade sizing + maker/taker
buys=trade[trade["side"].str.upper()=="BUY"]
print(f"\n=== sizing (BUY usdcSize) ===\n{buys['usdcSize'].describe(percentiles=[.5,.9,.99]).round(2).to_string()}")
print(f"\nentry price dist:\n{buys['price'].describe(percentiles=[.1,.5,.9]).round(3).to_string()}")
print(f"\nsaved per-market table -> cache/_331_per_market.csv")
