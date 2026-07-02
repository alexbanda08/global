"""T1 v2 — CORRECTED feed-loss audit.
BUG in v1: joined on trade.local_timestamp_us (= data-api POLL/write time, lags real trade 0-5s,
minutes on backfill) against the real-time WS book -> spurious 'invisible'. Collector also does
DEDUP-ON-CHANGE (gaps usually = book unchanged, NOT dropped).
FIX: join trade.timestamp_us (exchange match time, second-granular) -> book.timestamp_us (source ms),
with windows wide enough to absorb the 1s trade-rounding. If invisibility is still high with a
generous +-2/3s window, that's REAL WS loss; if it drops to ~0, v1 was a join artifact.
"""
import sys, time
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from load import load_resolutions, load_orderbook_l25_streaming, CANON

COIN="BTC"; TF="15m"; N=int(sys.argv[1]) if len(sys.argv)>1 else 50
WINDOWS=[1_000_000,2_000_000,3_000_000]
t0=time.time()
rnd=lambda x: np.round(np.asarray(x,float),2)

res=load_resolutions(assets=[COIN],timeframes=[TF]).drop_duplicates("slug").sort_values("slot_start_us")
lo=int(pd.Timestamp("2026-04-27",tz="UTC").timestamp()*1e6); hi=int(pd.Timestamp("2026-06-15",tz="UTC").timestamp()*1e6)
res=res[(res.slot_start_us>=lo)&(res.slot_start_us<=hi)]
sl_all=res.slug.tolist(); step=max(1,len(sl_all)//N); sample=set(sl_all[::step][:N])
print(f"T1v2: {COIN} {TF}, {len(sample)} slugs",flush=True)

p=CANON/"trades_polymarket"/f"{COIN.lower()}.parquet"
cols=["timestamp_us","local_timestamp_us","slug","outcome","price","size","side"]
parts=[]; pf=pq.ParquetFile(p)
for bt in pf.iter_batches(columns=cols,batch_size=500_000):
    d=bt.to_pandas(); d=d[d.slug.isin(sample)]
    if len(d): parts.append(d)
tr=pd.concat(parts,ignore_index=True)
tr["timestamp_us"]=pd.to_numeric(tr.timestamp_us,errors="coerce")
tr["local_timestamp_us"]=pd.to_numeric(tr.local_timestamp_us,errors="coerce")
tr=tr[np.isfinite(tr.timestamp_us)]; tr["price"]=rnd(tr.price)
lag=(tr.local_timestamp_us-tr.timestamp_us).dropna()/1e6
print(f"trades {len(tr)} | LAG local-exchange (s): p50={lag.median():.1f} p90={lag.quantile(.9):.1f} max={lag.max():.0f}  <- why v1 (local-join) was wrong",flush=True)

bks=load_orderbook_l25_streaming(COIN.lower(),slugs=sample,subsample_1hz=False)
print(f"L25 {len(bks)} series t={time.time()-t0:.0f}s",flush=True)

rows=[]; offs=[]
for (slug,oc),g in tr.groupby(["slug","outcome"]):
    rec=bks.get((slug,oc))
    if rec is None or len(rec[0])<2: continue
    ts,ap,asz,bp,bs=rec; ts=ts.astype(np.int64); apr=rnd(ap); bpr=rnd(bp)
    T=g.timestamp_us.to_numpy().astype(np.int64); P=g.price.to_numpy(); SZ=g["size"].to_numpy(); BUY=(g.side.to_numpy()=="buy")
    ts0=ts[0]; ts1=ts[-1]
    for k in range(len(T)):
        t=T[k]; price=round(float(P[k]),2); buy=BUY[k]
        relP=apr if buy else bpr; relS=asz if buy else bs
        # covered = trade falls inside the book series span (NOT in the late-start blind zone or post-end)
        r={"size":SZ[k],"buy":buy,"covered":bool(ts0<=t<=ts1),"pre_start":bool(t<ts0)}
        # nearest book snap offset (clock-alignment sanity)
        j=int(np.searchsorted(ts,t)); cand=[i for i in (j-1,j) if 0<=i<len(ts)]
        if cand: off=min(abs(ts[i]-t) for i in cand)/1e6; offs.append(off)
        for W in WINDOWS:
            m=np.abs(ts-t)<=W
            r[f"vis_{W}"]=bool(m.any() and price in set(np.round(relP[m][relS[m]>0],2)))
            if W==WINDOWS[-1]:
                anyp=set(np.round(apr[m][asz[m]>0],2))|set(np.round(bpr[m][bs[m]>0],2)) if m.any() else set()
                r["vis_any"]=price in anyp
        rows.append(r)
R=pd.DataFrame(rows)
print("="*66)
print(f"JOINED {len(R)} prints | nearest-snap offset p50={np.median(offs):.2f}s p90={np.percentile(offs,90):.2f}s (small=clocks aligned)")
for W in WINDOWS:
    inv=~R[f"vis_{W}"]
    print(f"  rel-side +-{W//1_000_000}s: INVISIBLE count={100*inv.mean():.1f}% vol={100*R.loc[inv,'size'].sum()/R['size'].sum():.1f}%")
inv=~R["vis_any"]
print(f"  any-side +-{WINDOWS[-1]//1_000_000}s: INVISIBLE count={100*inv.mean():.1f}% vol={100*R.loc[inv,'size'].sum()/R['size'].sum():.1f}%")
# coverage split: late-start blind zone vs steady-state covered region
pre=R[R.pre_start]; cov=R[R.covered]
print(f"\nCOVERAGE: pre-start(late-start blind) {len(pre)} prints ({100*len(pre)/len(R):.0f}%); covered {len(cov)} ({100*len(cov)/len(R):.0f}%)")
print(f"  pre-start fills are 100% invisible by construction (no book yet) — this is the ~116s LATE-START issue")
for W in WINDOWS:
    inv=~cov[f"vis_{W}"]
    print(f"  COVERED-only rel-side +-{W//1_000_000}s: INVISIBLE count={100*inv.mean():.1f}% vol={100*cov.loc[inv,'size'].sum()/cov['size'].sum():.1f}%")
inv=~cov["vis_any"]
print(f"  COVERED-only any-side +-3s: INVISIBLE count={100*inv.mean():.1f}% vol={100*cov.loc[inv,'size'].sum()/cov['size'].sum():.1f}%")
vb=1-cov["vis_any"].mean()
print(f"\nCORRECTED VERDICT — steady-state (covered) any-side +-3s invisible={100*vb:.1f}%: "
      +("real WS loss" if vb>=0.20 else ("FEED FINE — v1 'blind' was a join artifact; real issue = ~116s late-start" if vb<0.05 else "MODEST"))
      +f" | pre-start blind share of all fills={100*len(pre)/len(R):.0f}%")
print(f"t={time.time()-t0:.0f}s")
