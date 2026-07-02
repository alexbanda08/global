"""Size the MAKER opportunity from EXISTING data (full-book + trades), no deltas needed.
Decompose taker $-flow into:
  (A) AT-EXISTING-LEVEL  — price was a visible rel-side level (capturable by resting + FIFO queue patience; our sims already model this, hit ~4-7% capture ceiling)
  (B) INSIDE-SPREAD      — price BETTER than our best visible rel-side level = a new level appeared inside the spread & was taken (capturable ONLY by being FIRST = the article's speed/infra edge)
  (C) OTHER-INVISIBLE    — not visible & not inside-spread (deep walk beyond top-25, or transient)
If (B) is a big $ share at favorable prices -> the delta-sim + racer infra is worth building. If tiny -> save the effort.
Correct exchange-time join (timestamp_us), ±2s window. Hang-proof.
"""
import sys, time
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from load import load_resolutions, load_orderbook_l25_streaming, CANON

COIN="BTC"; TF="15m"; N=int(sys.argv[1]) if len(sys.argv)>1 else 50
W=2_000_000; SLUGS_PER_DAY=96  # btc-15m
t0=time.time(); rnd=lambda x: np.round(np.asarray(x,float),2)

res=load_resolutions(assets=[COIN],timeframes=[TF]).drop_duplicates("slug").sort_values("slot_start_us")
lo=int(pd.Timestamp("2026-04-27",tz="UTC").timestamp()*1e6); hi=int(pd.Timestamp("2026-06-15",tz="UTC").timestamp()*1e6)
res=res[(res.slot_start_us>=lo)&(res.slot_start_us<=hi)]
sa=res.slug.tolist(); step=max(1,len(sa)//N); sample=set(sa[::step][:N])
print(f"maker-opportunity: {COIN} {TF}, {len(sample)} slugs",flush=True)

p=CANON/"trades_polymarket"/f"{COIN.lower()}.parquet"
cols=["timestamp_us","slug","outcome","price","size","side"]; parts=[]
for bt in pq.ParquetFile(p).iter_batches(columns=cols,batch_size=500_000):
    d=bt.to_pandas(); d=d[d.slug.isin(sample)]
    if len(d): parts.append(d)
tr=pd.concat(parts,ignore_index=True); tr["timestamp_us"]=pd.to_numeric(tr.timestamp_us,errors="coerce")
tr=tr[np.isfinite(tr.timestamp_us)]; tr["price"]=rnd(tr.price)
bks=load_orderbook_l25_streaming(COIN.lower(),slugs=sample,subsample_1hz=False)
print(f"trades {len(tr)} | L25 {len(bks)} | t={time.time()-t0:.0f}s",flush=True)

rows=[]
for (slug,oc),g in tr.groupby(["slug","outcome"]):
    rec=bks.get((slug,oc))
    if rec is None or len(rec[0])<2: continue
    ts,ap,asz,bp,bs=rec; ts=ts.astype(np.int64); apr=rnd(ap); bpr=rnd(bp)
    T=g.timestamp_us.to_numpy().astype(np.int64); P=g.price.to_numpy(); SZ=g["size"].to_numpy(); BUY=(g.side.to_numpy()=="buy")
    ts0,ts1=ts[0],ts[-1]
    for k in range(len(T)):
        t=T[k]
        if not (ts0<=t<=ts1): continue  # covered only
        price=round(float(P[k]),2); sz=float(SZ[k]); buy=BUY[k]; notional=price*sz
        relP=apr if buy else bpr; relS=asz if buy else bs
        m=np.abs(ts-t)<=W
        if not m.any(): continue
        vis=price in set(np.round(relP[m][relS[m]>0],2))
        # best visible rel-side within window (best ask=min, best bid=max)
        pr=relP[m][relS[m]>0]; best=(pr.min() if buy else pr.max()) if pr.size else np.nan
        inside=bool(np.isfinite(best) and ((price<best-1e-9) if buy else (price>best+1e-9)))
        cls="A_at_level" if vis else ("B_inside_spread" if inside else "C_other")
        rows.append(dict(slug=slug,notional=notional,price=price,cls=cls,buy=buy))
R=pd.DataFrame(rows)
print("="*68)
tot=R.notional.sum(); nslug=R.slug.nunique()
print(f"COVERED taker flow: {len(R):,} fills, ${tot:,.0f} notional across {nslug} slugs (= ${tot/nslug:.0f}/slug)")
for c,lab in [("A_at_level","(A) AT-EXISTING-LEVEL  [rest+queue patience; our sims already model]"),
              ("B_inside_spread","(B) INSIDE-SPREAD       [needs BEING FIRST = article's speed/infra edge]"),
              ("C_other","(C) OTHER-INVISIBLE     [deep walk >L25 / transient]")]:
    s=R[R.cls==c]; usd=s.notional.sum()
    print(f"  {lab}\n      ${usd:,.0f}  ({100*usd/tot:.1f}% of flow)  {len(s):,} fills  ${usd/nslug:.1f}/slug")
b=R[R.cls=="B_inside_spread"]
if len(b):
    print(f"\nINSIDE-SPREAD (the first-mover opportunity) price bands ($ notional):")
    for los,his in [(0,0.3),(0.3,0.55),(0.55,0.85),(0.85,1.0)]:
        seg=b[(b.price>=los)&(b.price<his)]; print(f"  {los:.2f}-{his:.2f}: ${seg.notional.sum():,.0f} ({100*seg.notional.sum()/b.notional.sum():.0f}%)")
# scale to $/day and the b945-capture frame
flow_day=tot/nslug*SLUGS_PER_DAY
bshare=b.notional.sum()/tot
print(f"\nSCALE (btc-15m, {SLUGS_PER_DAY} slugs/day): total taker flow ~${flow_day:,.0f}/day")
print(f"  first-mover (B) opportunity ~${flow_day*bshare:,.0f}/day; b945 captures ~11.5% of TOTAL flow as maker")
print(f"  → at his ~0.8% edge-on-volume, total-flow capture ~${flow_day*0.115*0.008:,.0f}/day; (B) is the part our full-book sim CANNOT model")
print(f"t={time.time()-t0:.0f}s")
