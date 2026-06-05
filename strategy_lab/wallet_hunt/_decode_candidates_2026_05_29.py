"""Classify the harvested NEW candidates by strategy.

These trade INTRADAY cells (btc-5m/15m, sol/eth-15m) that ARE in canonical resolutions,
so we can join to true outcomes. For each wallet:
  - activity composition + maker_rebate_share (maker vs taker) + SPLIT (mint?)
  - side mix, timeframe/cell mix
  - directional decode vs canonical outcome: dominant-side hit-rate ($ and raw),
    avg entry px when winner vs loser, est PnL of dominant side
  - FIFO complete-set pair sum (lock-the-lag test): median, %<1
  - verdict heuristic
"""
from __future__ import annotations
import json, sys
from collections import deque, defaultdict
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "data" / "v4" / "canonical"))
from load import load_resolutions          # noqa
from cash_pnl import cash_pnl, maker_rebate_share  # noqa
from polymarket_api import fetch_lb_profit, lb_amount  # noqa

PORT = HERE / "cache" / "_pm_portfolio"
CANDS = {
    "0x3c58ef42": "0x3c58ef422754ff22c7e806336feba0064d8b776b",
    "0xd9dea316": "0xd9dea316cd3b785828bfa7c41ef081a4684b608b",
    "0x251c1a28": "0x251c1a283703beed41590b0875a8dcb8ddd1541f",
    "0xc387c2a4": "0xc387c2a40d389f17b723b6bba9b18b7dbd2de4f4",
    "0x5e2b9261": "0x5e2b9261b0c4f697b55bf921ff2bc227183d9101",
}

def load(short):
    frames=[]
    for t in ["TRADE","MERGE","SPLIT","REDEEM","MAKER_REBATE","REWARD","CONVERSION"]:
        f=PORT/short/f"activity_{t}.json"
        if f.exists():
            a=json.load(open(f,encoding="utf-8"))
            if a: dd=pd.DataFrame(a); dd["type"]=t; frames.append(dd)
    if not frames: return pd.DataFrame()
    df=pd.concat(frames,ignore_index=True,sort=False)
    for c in ["price","size","usdcSize","timestamp"]:
        if c in df.columns: df[c]=pd.to_numeric(df[c],errors="coerce")
    for c in ["slug","outcome","side","conditionId"]: df[c]=df.get(c,"").fillna("")
    return df

def fifo_pairs(g):
    g=g.sort_values("timestamp")
    top2=g.groupby("outcome")["size"].sum().sort_values(ascending=False).head(2).index.tolist()
    if len(top2)<2: return []
    A,B=top2; qA,qB=deque(),deque(); pairs=[]
    for _,r in g.iterrows():
        o,p,n,ts=r["outcome"],float(r["price"]),float(r["size"]),int(r["timestamp"])
        if o==A: my,opp=qA,qB
        elif o==B: my,opp=qB,qA
        else: continue
        while n>1e-9 and opp:
            op_px,op_ts,op_sh=opp[0]; m=min(n,op_sh)
            pairs.append((op_px+p,m,abs(ts-op_ts))); n-=m; op_sh-=m
            if op_sh<=1e-9: opp.popleft()
            else: opp[0][2]=op_sh
        if n>1e-9: my.append([p,ts,n])
    return pairs

def decode(short, full, res):
    df=load(short)
    if df.empty: print(f"\n{short}: NO ACTIVITY (pull may have failed)"); return
    tr=df[df.type=="TRADE"].copy()
    tr["usd"]=tr["usdcSize"].fillna(tr["size"]*tr["price"])
    comp={t:int((df.type==t).sum()) for t in df.type.unique()}
    reb=maker_rebate_share(df); res_pnl=cash_pnl(df)
    lb=fetch_lb_profit(full,use_cache=True)
    # cell mix
    tr["cell"]=tr["slug"].str.extract(r"^([a-z0-9]+-updown-\d+[mh])")[0]
    cellmix=tr.groupby("cell")["usd"].sum().sort_values(ascending=False)
    sidemix=tr["side"].value_counts().to_dict()
    # directional decode vs canonical outcome
    rows=[]; pair_sums=[]
    for cond,g in tr.groupby("conditionId"):
        slug=g["slug"].iloc[0]
        b=g[g.side.str.upper()=="BUY"]
        if not len(b): continue
        agg=b.groupby("outcome").agg(sh=("size","sum"),usd=("usd","sum"))
        if not len(agg): continue
        agg["px"]=agg["usd"]/agg["sh"]
        dom=agg["usd"].idxmax(); d=agg.loc[dom]
        win=res.get(slug)
        for s,_,_ in []: pass
        for ps in fifo_pairs(b): pair_sums.append(ps)
        rows.append(dict(slug=slug, dom=dom, dom_usd=float(d["usd"]), dom_sh=float(d["sh"]),
            dom_px=float(d["px"]), nout=len(agg),
            skew=float(d["usd"]/agg["usd"].sum()), winner=win,
            dom_is_winner=(dom==win) if win else None))
    m=pd.DataFrame(rows)
    matched=m[m["winner"].notna()]
    print(f"\n===== {short}  lb_all=${lb_amount(lb,'all')} 7d=${lb_amount(lb,'7d')} 1d=${lb_amount(lb,'1d')} =====")
    print(f"  activity: {comp}")
    print(f"  maker_rebate_share={reb:.4f} ({'MAKER' if reb>0.05 else 'TAKER'})  side_mix={sidemix}")
    print(f"  cell $: {{{', '.join(f'{k}:{v:,.0f}' for k,v in cellmix.items() if pd.notna(k))}}}")
    print(f"  slugs traded={len(m)}  matched-to-canonical-outcome={len(matched)}  avg_outcomes/slug={m.nout.mean():.2f}")
    if len(matched):
        hit=matched.dom_is_winner.mean(); wsum=matched.dom_usd.sum()
        whit=matched.loc[matched.dom_is_winner==True,"dom_usd"].sum()/wsum if wsum else np.nan
        w=matched[matched.dom_is_winner==True]; l=matched[matched.dom_is_winner==False]
        print(f"  DIRECTIONAL hit-rate dom-side: {100*hit:.1f}%  ($-weighted {100*whit:.1f}%)  median skew={100*matched.skew.median():.0f}%")
        print(f"  avg dom entry px WIN={w.dom_px.mean():.3f}(n={len(w)}) LOSE={l.dom_px.mean():.3f}(n={len(l)})")
        epnl=matched.apply(lambda r: r.dom_sh*(1-r.dom_px) if r.dom_is_winner else -r.dom_sh*r.dom_px,axis=1).sum()
        print(f"  est PnL dom-side held to $1: ${epnl:,.0f} over {len(matched)} slugs")
    if pair_sums:
        ps=pd.DataFrame(pair_sums,columns=["sum","sh","gap"])
        wmed=ps.sort_values("sum"); cum=wmed.sh.cumsum(); med=wmed.loc[cum>=0.5*wmed.sh.sum(),"sum"].iloc[0]
        lt1=(ps.loc[ps["sum"]<1,"sh"].sum()/ps.sh.sum())
        print(f"  FIFO pair-sum median={med:.3f}  %<1(sh-wtd)={100*lt1:.1f}%  median_gap={ps.gap.median():.0f}s  (lock test)")
    # verdict
    v=[]
    if reb>0.05: v.append("MAKER(rebates)")
    else: v.append("taker")
    if len(matched) and matched.skew.median()>0.7: v.append("one-sided/directional")
    if comp.get("SPLIT",0)>5: v.append("mints(SPLIT)")
    if comp.get("MERGE",0)>5: v.append("merges")
    print(f"  >>> signature: {', '.join(v)}")

if __name__=="__main__":
    r=load_resolutions()[["slug","outcome"]].drop_duplicates("slug").set_index("slug")["outcome"]
    for s,f in CANDS.items():
        decode(s,f,r)
