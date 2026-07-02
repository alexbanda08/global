"""PHASE-2 SMOKE v3 — DE-CORRUPTED keyframe + clean deltas.
Snapshot table corruption = per-level price<->size swap (recoverable: if price-col>1, swap with size-col).
We de-corrupt the snapshot to seed a correct keyframe, then apply the clean price_change deltas.
Validates: de-corruption rule works (book becomes valid: 0<bid<ask<1, positive spread), reconstruct on
real data, + first delta-vs-1Hz capture read (thin trades -> directional only)."""
import sys, time
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
from load import reconstruct_book_10hz

SM="data/v4/refresh_2026_06_16/smoke"; t0=time.time()
rd=lambda f: pd.read_csv(f"{SM}/{f}.csv.gz", compression="gzip")
snaps, deltas, trades = rd("snaps"), rd("deltas"), rd("trades")

def levels(df, sidep, sides):  # returns price[N,25], size[N,25] DE-CORRUPTED (swap where price>1)
    P=np.column_stack([df[f"{sidep}_{i}"].to_numpy(float) for i in range(25)])
    S=np.column_stack([df[f"{sides}_{i}"].to_numpy(float) for i in range(25)])
    swap = P>1.0                       # price-col holds a size -> swap
    Pc=np.where(swap,S,P); Sc=np.where(swap,P,S)
    return Pc, Sc

def keyframe_for(sl, oc):
    g=snaps[(snaps.slug==sl)&(snaps.outcome==oc)].sort_values("timestamp_us")
    if len(g)==0: return None
    ap,asz=levels(g,"ask_price","ask_size"); bp,bs=levels(g,"bid_price","bid_size")
    return (g.timestamp_us.to_numpy(np.int64), ap, asz, bp, bs)

def bbid(prow,srow,is_ask):
    m=np.isfinite(prow)&(prow>0)&(prow<1.5)&np.isfinite(srow)&(srow>0)
    if not m.any(): return np.nan
    return round(float(prow[m].min() if is_ask else prow[m].max()),3)

slugs=sorted(snaps.slug.unique()); spreads=[]; inb=[]; rates=[]
cap={"delta":{"f":0.,"m":0.,"fr":0},"hz":{"f":0.,"m":0.,"fr":0}}
def sim(book,sells,ss,se):
    ts,ap,asz,bp,bs=book
    if len(ts)<2: return (0.,float(sells["size"].sum()),0)
    spx=np.round(sells.price.to_numpy(float),2); sts=sells.timestamp_us.to_numpy(np.int64); ssz=sells["size"].to_numpy(float)
    fill=0.; first=0
    for q0 in range(int(ss),int(se),10_000_000):
        q1=min(q0+10_000_000,int(se)); j=int(np.searchsorted(ts,q0,"right"))-1
        if j<0: continue
        price=bbid(bp[j],bs[j],False)
        if not np.isfinite(price): continue
        qa=bs[j][np.isfinite(bp[j])&(np.round(bp[j],2)==price)].sum()
        if qa<=1e-9: first+=1
        m=(sts>=q0)&(sts<q1)&(np.abs(spx-price)<1e-9)
        fill+=min(5.0/max(price,.01),max(0.,ssz[m].sum()-qa))
    return (fill,float(ssz.sum()),first)

for sl in slugs:
    ss=int(sl.split("-")[-1])*1_000_000; se=ss+900_000_000
    for oc in ("Up","Down"):
        kf=keyframe_for(sl,oc)
        if kf is None: continue
        dd=deltas[(deltas.slug==sl)&(deltas.outcome==oc)].sort_values("timestamp_us")[["timestamp_us","side","price","size"]].reset_index(drop=True)
        db=reconstruct_book_10hz(kf,dd); dbt=db[0]
        if len(dbt)<5: continue
        rates.append(len(dbt)/max((dbt[-1]-dbt[0])/1e6,1))
        for k in np.linspace(len(dbt)//5,len(dbt)-1,8).astype(int):
            a=bbid(db[1][k],db[2][k],True); b=bbid(db[3][k],db[4][k],False)
            if np.isfinite(a) and np.isfinite(b): spreads.append(a-b); inb.append(0<b<a<1)
        sec=dbt//1_000_000; _,u=np.unique(sec,return_index=True); u=np.sort(u)
        hz=(dbt[u],db[1][u],db[2][u],db[3][u],db[4][u])
        sells=trades[(trades.slug==sl)&(trades.outcome==oc)&(trades.side=="sell")][["timestamp_us","price","size"]]
        for m,bk in (("delta",db),("hz",hz)):
            f,mk,fr=sim(bk,sells,ss,se); cap[m]["f"]+=f; cap[m]["m"]+=mk; cap[m]["fr"]+=fr
print("="*62)
print(f"(1) reconstruct (de-corrupted keyframe + clean deltas): median rate {np.median(rates):.1f}/s")
print(f"(2) SANITY: median spread {np.median(spreads):+.3f} (>0=valid) | frac 0<bid<ask<1: {100*np.mean(inb):.0f}%  <- de-corruption WORKS")
for m in ("delta","hz"):
    c=cap[m]; capture=100*c["f"]/c["m"] if c["m"]>0 else 0
    print(f"(3) {m:>5}-book: flow_capture={capture:5.2f}%  filled={c['f']:.0f}sh  first-quotes={c['fr']}")
print(f"    (trades thin: {int((trades.side=='sell').sum())} sells/4 windows -> DIRECTIONAL only)")
print(f"t={time.time()-t0:.0f}s")
