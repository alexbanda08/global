"""Decode 0xee65685d (high-volume maker, $33.9M vol, +$177k). Feed capped at 3500
TRADE/REDEEM so $ is recent-slice only; anchor lifetime on lb-api."""
import sys, re
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt")
import pandas as pd, numpy as np
from polymarket_api import fetch_activity, activity_to_df, fetch_lb_profit, fetch_lb_volume, lb_amount

W="0xee65685de42f8de9a03b4c53ee77d56a20d2cfc9"
OUT=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache"
df=activity_to_df(fetch_activity(W,use_cache=True))
for c in ["usdcSize","size","price","timestamp"]: df[c]=pd.to_numeric(df[c],errors="coerce")
df["dt"]=pd.to_datetime(df["timestamp"],unit="s"); df["title"]=df["title"].astype(str)
def cat(t):
    t=t.lower()
    if re.search(r"up or down|up/down",t): return "crypto-updown"
    if re.search(r"temperature|°|weather",t): return "weather"
    if re.search(r"launch a token|token by",t): return "token-launch"
    if re.search(r"hit \(|hit \$|dip to|reach \$|between \$",t): return "price-touch/range"
    if re.search(r"bitcoin|ethereum|solana|\bbtc\b|\beth\b|\bsol\b|\bxrp\b",t): return "crypto-other"
    if re.search(r"trump|election|president|senate|fed|rate|nominat",t): return "politics/macro"
    if re.search(r"vs\.?|win|beat|game|match|nba|nfl|mlb|soccer|ufc",t): return "sports"
    return "other"
df["cat"]=df["title"].map(cat)
tr=df[df["type"]=="TRADE"].copy()
print("="*64)
lb=fetch_lb_profit(W); vol=fetch_lb_volume(W)
print(f"OFFICIAL: lifetime=${lb_amount(lb,'all'):,.0f} 30d=${lb_amount(lb,'30d'):,.0f} 7d=${lb_amount(lb,'7d'):,.0f}")
print(f"volume all=${lb_amount(vol,'all'):,.0f} 30d=${lb_amount(vol,'30d'):,.0f}")
print(f"feed span {df['dt'].min()} -> {df['dt'].max()} | TRADE {len(tr)} REDEEM {(df['type']=='REDEEM').sum()} MAKER_REBATE {(df['type']=='MAKER_REBATE').sum()}")
print(f"side split: {tr['side'].str.upper().value_counts().to_dict()}")
print(f"\n-- category mix (trades) --\n{tr.groupby('cat').agg(n=('usdcSize','size'),notional=('usdcSize','sum')).round(0).sort_values('notional',ascending=False).to_string()}")
# maker vs taker proxy: side BUY/SELL counts + rebate
print(f"\nMAKER_REBATE total $: {df[df.type=='MAKER_REBATE']['usdcSize'].sum():.2f} (rebate income => maker)")
b=tr[tr.side.str.upper()=='BUY']; s=tr[tr.side.str.upper()=='SELL']
print(f"\n-- sizing usdcSize: BUY med=${b.usdcSize.median():.1f} mean=${b.usdcSize.mean():.1f} p99=${b.usdcSize.quantile(.99):.0f} max=${b.usdcSize.max():.0f}")
print(f"entry price: med={b.price.median():.3f} p10={b.price.quantile(.1):.3f} p90={b.price.quantile(.9):.3f}")
# per-market cash (recent complete slice only)
rows=[]
for cid,sub in df.groupby("conditionId"):
    bb=sub[(sub.type=='TRADE')&(sub.side.str.upper()=='BUY')]; ss=sub[(sub.type=='TRADE')&(sub.side.str.upper()=='SELL')]
    rd=sub[sub.type.isin(['REDEEM','REWARD','MAKER_REBATE'])]
    cost=bb.usdcSize.sum(); proc=ss.usdcSize.sum()+rd.usdcSize.sum()
    rows.append({"title":sub.title.iloc[0][:55],"cat":cat(sub.title.iloc[0]),"n_buy":len(bb),"n_sell":len(ss),
                 "cost":round(cost,2),"net":round(proc-cost,2),"first":sub.dt.min(),"last":sub.dt.max()})
mk=pd.DataFrame(rows)
mk["hold_min"]=((mk["last"]-mk["first"]).dt.total_seconds()/60).round(1)
print(f"\n-- markets touched (feed slice): {len(mk)} | median hold {mk.hold_min.median():.1f} min | by cat:")
print(mk.groupby('cat').agg(n=('net','size'),net=('net','sum')).round(0).sort_values('n',ascending=False).to_string())
print(f"\nexit style: {s.shape[0]} sells vs {(df.type=='REDEEM').sum()} redeems -> {'SELL-flip (MM)' if s.shape[0]>(df.type=='REDEEM').sum()*0.5 else 'hold-to-resolution'}")
mk.to_csv(OUT+r"\_ee65_per_market.csv",index=False)
print("saved -> cache/_ee65_per_market.csv")
