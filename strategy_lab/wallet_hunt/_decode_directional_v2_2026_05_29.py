"""Directional decode v2 for the 4 maker wallets (binary markets only).

Fixes the `Series.size` attribute bug (use df['size'] bracket access).
Per binary market (daily_updown + target_price + hourly), compute:
  - net BUY shares & $ per outcome, avg fill price per outcome
  - dominant side ($-weighted), skew, winner (outcome whose last trade px -> 1)
  - did wallet hold the WINNING side dominantly? (directional hit rate)
  - avg entry px of dominant side; est PnL if held to $1 redemption
Aggregate: directional hit-rate, $-weighted hit-rate, avg winner-cost,
sum-cost of complete-set-matched portion (true arb test).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
PORT = HERE / "cache" / "_pm_portfolio"
OUT = HERE / "cache" / "_maker_decode_2026_05_29"
OUT.mkdir(parents=True, exist_ok=True)

WALLETS = {
    "0fe40e88": "gobblewobble",
    "4ee29e4e": "IH2P",
    "a42f127d": "5f5a",
    "143732d8": "multisafe",
}

def load(short):
    frames=[]
    d = "0x"+short if not short.startswith("0x") else short
    for t in ["TRADE","MERGE","SPLIT","REDEEM","MAKER_REBATE"]:
        f=PORT/d/f"activity_{t}.json"
        if f.exists():
            a=json.load(open(f,encoding="utf-8"))
            if a:
                dd=pd.DataFrame(a); dd["type"]=t; frames.append(dd)
    if not frames: return pd.DataFrame()
    df=pd.concat(frames,ignore_index=True,sort=False)
    for c in ["price","size","usdcSize","timestamp","outcomeIndex"]:
        if c in df.columns: df[c]=pd.to_numeric(df[c],errors="coerce")
    for c in ["slug","outcome","side","conditionId","title"]:
        df[c]=df.get(c,"").fillna("")
    return df

def kind(slug):
    s=slug.lower()
    if "up-or-down-on" in s: return "daily_updown"
    if "up-or-down" in s: return "hourly_updown"
    if any(k in s for k in ["what-price-will","price-on","above-on","reach","-hit-"]): return "target_price"
    return "other"

def decode(short):
    df=load(short)
    if df.empty: print(short,"empty"); return
    tr=df[df.type=="TRADE"].copy()
    tr["kind"]=tr["slug"].map(kind)
    rows=[]
    for cond,g in df.groupby("conditionId"):
        if not cond: continue
        gt=g[g.type=="TRADE"]
        if not len(gt): continue
        slug=gt["slug"].iloc[0]; k=kind(slug)
        # binary markets only: exactly 2 distinct outcomes traded, names look binary
        outs=sorted(gt["outcome"].unique().tolist())
        b=gt[gt.side.str.upper()=="BUY"]
        s=gt[gt.side.str.upper()=="SELL"]
        if not len(b): continue
        agg=b.groupby("outcome").apply(lambda x: pd.Series({
            "shares":x["size"].sum(),"usd":x["usdcSize"].sum()})).reset_index()
        agg["avgpx"]=agg["usd"]/agg["shares"].replace(0,np.nan)
        # winner proxy = outcome with highest LAST trade price in this market
        last_px=gt.sort_values("timestamp").groupby("outcome")["price"].last()
        winner=last_px.idxmax() if len(last_px) else None
        win_last=float(last_px.max()) if len(last_px) else np.nan
        # dominant side by $ bought
        dom=agg.sort_values("usd",ascending=False).iloc[0]
        dom_out=dom["outcome"]; dom_usd=float(dom["usd"]); dom_sh=float(dom["shares"]); dom_px=float(dom["avgpx"])
        tot_usd=float(agg["usd"].sum())
        skew=dom_usd/tot_usd if tot_usd else np.nan
        # complete-set matched (true arb portion): min shares across the 2 biggest outcomes
        if len(agg)>=2:
            two=agg.sort_values("shares",ascending=False).head(2)
            matched=float(two["shares"].min())
            sum_cost=float(two["avgpx"].sum())  # px(out1)+px(out2)
        else:
            matched=0.0; sum_cost=np.nan
        n_redeem=int((g.type=="REDEEM").sum()); n_merge=int((g.type=="MERGE").sum())
        n_split=int((g.type=="SPLIT").sum())
        rows.append(dict(cond=cond,slug=slug,kind=k,n_out=len(agg),
            dom_out=dom_out,dom_usd=dom_usd,dom_sh=dom_sh,dom_avgpx=dom_px,skew=skew,
            tot_usd=tot_usd,winner=winner,win_last=win_last,
            dom_is_winner=(dom_out==winner) if winner else None,
            matched_shares=matched,pair_sum_cost=sum_cost,
            n_redeem=n_redeem,n_merge=n_merge,n_split=n_split,
            n_sell=len(s),sell_usd=float(s["usdcSize"].sum()) if len(s) else 0.0))
    md=pd.DataFrame(rows)
    md.to_parquet(OUT/f"{short}_dirmarkets.parquet",index=False)

    # focus on binary up-down markets (where winner proxy is reliable: 2 outcomes, last px clearly converged)
    bm=md[(md.n_out==2)&(md.kind.isin(["daily_updown","hourly_updown","target_price"]))].copy()
    conv=bm[bm.win_last>=0.85]  # markets that actually converged (resolved-ish)
    print(f"\n===== {short} ({WALLETS[short]}) =====")
    print(f"  binary markets traded: {len(bm)}  (converged win_last>=0.85: {len(conv)})")
    if len(conv):
        hit=conv["dom_is_winner"].mean()
        # $-weighted hit
        wsum=conv["dom_usd"].sum()
        whit=(conv.loc[conv.dom_is_winner==True,"dom_usd"].sum())/wsum if wsum else np.nan
        print(f"  DIRECTIONAL HIT-RATE (dominant side = winner): {100*hit:.1f}%  | $-weighted: {100*whit:.1f}%")
        print(f"  median $-skew toward dominant side: {100*conv['skew'].median():.1f}%  (50%=balanced,100%=one-sided)")
        win_rows=conv[conv.dom_is_winner==True]; los_rows=conv[conv.dom_is_winner==False]
        print(f"  avg dom-side entry px  WHEN WINNER: {win_rows['dom_avgpx'].mean():.3f} (n={len(win_rows)})  WHEN LOSER: {los_rows['dom_avgpx'].mean():.3f} (n={len(los_rows)})")
        # est pnl: dominant side held to redemption: win-> shares*(1-avgpx); lose-> -shares*avgpx
        def epnl(r):
            return r.dom_sh*(1-r.dom_avgpx) if r.dom_is_winner else -r.dom_sh*r.dom_avgpx
        conv=conv.assign(est_dom_pnl=conv.apply(epnl,axis=1))
        print(f"  est PnL if ONLY dominant side held to $1: ${conv['est_dom_pnl'].sum():,.0f} over {len(conv)} markets")
        print(f"  complete-set matched pair_sum_cost median: {conv['pair_sum_cost'].median():.4f}  (<1 => arb portion)")
        # arb portion size
        conv=conv.assign(arb_usd=conv["matched_shares"]*conv["pair_sum_cost"])
        print(f"  matched(complete-set) buy$ ~= ${conv['arb_usd'].sum():,.0f} vs total dom buy$ ${conv['dom_usd'].sum():,.0f}")
    # kind notional
    kn=tr.groupby("kind")["usdcSize"].sum().sort_values(ascending=False)
    print(f"  trade $ by kind: {{{', '.join(f'{k}:{v:,.0f}' for k,v in kn.items())}}}")

if __name__=="__main__":
    for s in WALLETS: decode(s)
    print(f"\nsaved -> {OUT}")
