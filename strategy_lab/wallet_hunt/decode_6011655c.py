"""Decode 0x6011655c (@hightemptation 'HighTempTation'). Full activity tape
(1292 trades, not capped). Category, buy/sell, per-market cash PnL, hold time, sizing."""
import sys, re
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt")
import pandas as pd, numpy as np
from polymarket_api import fetch_activity, activity_to_df
W="0x6011655c4afb76f36dd1b08a137a1ba73466b31e"
OUT=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache"
df=activity_to_df(fetch_activity(W,use_cache=True))
for c in ["usdcSize","size","price","timestamp"]: df[c]=pd.to_numeric(df[c],errors="coerce")
df["dt"]=pd.to_datetime(df["timestamp"],unit="s"); df["title"]=df["title"].astype(str)
def cat(t):
    t=t.lower()
    if re.search(r"temperature|°|degrees|warmest|coldest|hottest|weather|rain|snow",t): return "weather"
    if re.search(r"launch a token|token by",t): return "token-launch"
    if re.search(r"up or down|bitcoin|ethereum|solana|\bbtc\b|\beth\b|\bsol\b",t): return "crypto-updown"
    if re.search(r"hit \(|hit \$|\$[0-9].* in (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",t): return "price-touch"
    return "other"
df["cat"]=df["title"].map(cat)
tr=df[df["type"]=="TRADE"].copy()
print(f"span {df['dt'].min()} -> {df['dt'].max()} | TRADE {len(tr)} REDEEM {(df['type']=='REDEEM').sum()}")
print(f"side split: {tr['side'].str.upper().value_counts().to_dict()}")
print(f"\n-- category mix (all trades) --\n{tr.groupby('cat').agg(n=('usdcSize','size'),notional=('usdcSize','sum')).round(0).sort_values('notional',ascending=False).to_string()}")
buys=tr[tr.side.str.upper()=="BUY"]; sells=tr[tr.side.str.upper()=="SELL"]
print(f"\n-- BUY notional --\n{buys['usdcSize'].describe(percentiles=[.5,.9]).round(2).to_string()}")
print(f"entry price: median={buys['price'].median():.3f} p10={buys['price'].quantile(.1):.3f} p90={buys['price'].quantile(.9):.3f}")
# per-market cash pnl (full window, feed complete)
rows=[]
for cid,s in df.groupby("conditionId"):
    b=s[(s.type=="TRADE")&(s.side.str.upper()=="BUY")]; se=s[(s.type=="TRADE")&(s.side.str.upper()=="SELL")]
    rd=s[s.type.isin(["REDEEM","REWARD","REFERRAL_REWARD","MAKER_REBATE"])]
    cost=b.usdcSize.sum(); proc=se.usdcSize.sum()+rd.usdcSize.sum()
    if len(b)==0 and len(se)==0: continue
    rows.append({"title":s.title.iloc[0][:62],"cat":cat(s.title.iloc[0]),"n_buy":len(b),"n_sell":len(se),
                 "n_redeem":len(rd),"cost":round(cost,2),"proceeds":round(proc,2),"net":round(proc-cost,2),
                 "first":s.dt.min(),"last":s.dt.max(),"won":int(proc>cost)})
mk=pd.DataFrame(rows).sort_values("net",ascending=False)
mk["hold_hr"]=((mk["last"]-mk["first"]).dt.total_seconds()/3600).round(1)
mk.to_csv(OUT+r"\_6011_per_market.csv",index=False)
print(f"\n=== PER-MARKET (n={len(mk)}) total realized net=${mk.net.sum():,.0f} | market-WR={mk.won.mean()*100:.1f}% | median hold={mk.hold_hr.median():.1f}h ===")
print(f"exits via SELL: {mk.n_sell.sum()} sells vs {mk.n_redeem.sum()} redeems -> {'SELL-out (flip) strategy' if mk.n_sell.sum()>mk.n_redeem.sum() else 'hold-to-resolution'}")
print("\n-- by category --")
bc=mk.groupby("cat").agg(n=("net","size"),cost=("cost","sum"),net=("net","sum"),wr=("won","mean"))
bc["wr"]=(bc.wr*100).round(1); bc[["cost","net"]]=bc[["cost","net"]].round(0)
print(bc.sort_values("net",ascending=False).to_string())
print("\n-- monthly --")
mk["ym"]=mk["last"].dt.to_period("M")
mo=mk.groupby("ym").agg(n=("net","size"),net=("net","sum")); mo["wr"]=(mk.groupby("ym")["won"].mean()*100).round(1)
mo["net"]=mo["net"].round(0); print(mo.to_string())
print("\n-- TOP 10 / WORST 6 markets --")
print(mk.head(10)[["title","cat","cost","net","hold_hr","last"]].to_string(index=False))
print("...")
print(mk.tail(6)[["title","cat","cost","net","hold_hr"]].to_string(index=False))
print("\nsaved -> cache/_6011_per_market.csv")
