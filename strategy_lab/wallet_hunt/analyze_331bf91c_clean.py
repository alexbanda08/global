"""0x331bf91c clean analysis — restrict $ PnL to the window where the TRADE feed
is complete (>= 2026-02-20, the 3500-trade cap floor). Official lifetime PnL from
lb-api is the truth for all-time; tape gives reliable detail only for this window."""
import sys, re
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt")
import pandas as pd, numpy as np
from polymarket_api import fetch_activity, activity_to_df, fetch_lb_profit, fetch_lb_volume, lb_amount

W="0x331bf91c132af9d921e1908ca0979363fc47193f"
OUT=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache"
CUT=pd.Timestamp("2026-02-20 12:47:04")   # earliest captured TRADE
df=activity_to_df(fetch_activity(W,use_cache=True))
for c in ["usdcSize","size","price","timestamp"]: df[c]=pd.to_numeric(df[c],errors="coerce")
df["dt"]=pd.to_datetime(df["timestamp"],unit="s"); df["title"]=df["title"].astype(str)

def cat(t):
    t=t.lower()
    if re.search(r"temperature|°|degrees|warmest|coldest|hottest|weather|rain|snow|precip",t): return "weather"
    if re.search(r"up or down|bitcoin|ethereum|solana|\bbtc\b|\beth\b|\bsol\b",t): return "crypto"
    return "other"

# per-market, only markets whose FIRST activity is in the complete-feed window
rows=[]
for cid,sub in df.groupby("conditionId"):
    if sub["dt"].min() < CUT: continue          # buys would be truncated -> skip
    buys=sub[(sub.type=="TRADE")&(sub.side.str.upper()=="BUY")]
    sells=sub[(sub.type=="TRADE")&(sub.side.str.upper()=="SELL")]
    rdm=sub[sub.type.isin(["REDEEM","REWARD","REFERRAL_REWARD","MAKER_REBATE"])]
    cost=buys.usdcSize.sum(); proceeds=sells.usdcSize.sum()+rdm.usdcSize.sum()
    rows.append({"title":sub.title.iloc[0][:75],"cat":cat(sub.title.iloc[0]),
                 "n_buys":len(buys),"n_sells":len(sells),"cost":round(cost,2),
                 "proceeds":round(proceeds,2),"net":round(proceeds-cost,2),
                 "avg_entry":round(buys.price.mean(),3) if len(buys) else None,
                 "last":sub.dt.max(),"won":int(proceeds>cost)})
mk=pd.DataFrame(rows).sort_values("net",ascending=False)
mk.to_csv(OUT+r"\_331_clean_per_market.csv",index=False)

lb=fetch_lb_profit(W); vol=fetch_lb_volume(W)
print("="*70)
print(f"0x331bf91c — OFFICIAL (lb-api, truth): lifetime=${lb_amount(lb,'all'):,.0f} | "
      f"30d=${lb_amount(lb,'30d'):,.0f} | 7d=${lb_amount(lb,'7d'):,.0f}")
print(f"volume: all=${lb_amount(vol,'all'):,.0f} | 30d=${lb_amount(vol,'30d'):,.0f}")
print("="*70)
print(f"\nCLEAN WINDOW (>= 2026-02-20, complete TRADE feed): {len(mk)} markets")
print(f"realized net=${mk.net.sum():,.0f} | cost deployed=${mk.cost.sum():,.0f} | "
      f"ROI={100*mk.net.sum()/mk.cost.sum():.1f}% | market-WR={mk.won.mean()*100:.1f}%")

print("\n--- BY CATEGORY (clean window) ---")
bc=mk.groupby("cat").agg(n=("net","size"),cost=("cost","sum"),net=("net","sum"),wr=("won","mean"))
bc["wr"]=(bc.wr*100).round(1); bc[["cost","net"]]=bc[["cost","net"]].round(0)
print(bc.sort_values("net",ascending=False).to_string())

print("\n--- MONTHLY (clean window): net / cost / WR / n ---")
mk["ym"]=mk["last"].dt.to_period("M")
mo=mk.groupby("ym").agg(n=("net","size"),cost=("cost","sum"),net=("net","sum"))
mo["wr"]=(mk.groupby("ym")["won"].mean()*100).round(1); mo[["cost","net"]]=mo[["cost","net"]].round(0)
print(mo.to_string())

print("\n--- TOP 10 / WORST 10 markets (clean window) ---")
print(mk.head(10)[["title","cost","net","avg_entry","last"]].to_string(index=False))
print("...")
print(mk.tail(10)[["title","cost","net","avg_entry","last"]].to_string(index=False))

buys=df[(df.type=="TRADE")&(df.side.str.upper()=="BUY")&(df.dt>=CUT)]
print(f"\n--- sizing/entry (clean window buys, n={len(buys)}) ---")
print(f"usdcSize: median=${buys.usdcSize.median():.1f} mean=${buys.usdcSize.mean():.1f} p90=${buys.usdcSize.quantile(.9):.0f} max=${buys.usdcSize.max():.0f}")
print(f"entry price: median={buys.price.median():.3f} (p10={buys.price.quantile(.1):.3f} p90={buys.price.quantile(.9):.3f})")
print(f"\nsaved -> cache/_331_clean_per_market.csv")
