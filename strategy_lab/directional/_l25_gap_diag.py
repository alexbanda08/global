"""L25 gap mechanism diagnostic. Characterize WHY canonical L25 has multi-second gaps.
Distinguishes: (1) event-driven sparsity (benign-ish), (2) 10Hz poller stalling,
(3) mid-window DATA STOP (the merge ts>prev poison-row drop bug), (4) book-moved-across-gap (real loss).
Small sample, hang-proof."""
import sys, time
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
from load import load_resolutions, load_orderbook_l25_streaming

COIN="BTC"; TF="15m"; N=int(sys.argv[1]) if len(sys.argv)>1 else 12
res=load_resolutions(assets=[COIN],timeframes=[TF]).drop_duplicates("slug").sort_values("slot_start_us")
# recent active window
res=res[res.slot_start_us>=int(pd.Timestamp("2026-06-10",tz="UTC").timestamp()*1e6)]
slugs=res.slug.tolist()[::max(1,len(res)//N)][:N]
smap=dict(zip(res.slug,res.slot_start_us))
bks=load_orderbook_l25_streaming(COIN.lower(),slugs=set(slugs),subsample_1hz=False)
print(f"{COIN} {TF}: {len(slugs)} slugs, {len(bks)} series\n"+"="*72)

GB=[0,.05,.15,.3,1,5,30,1e9]; GL=["<50ms","50-150","150-300ms","300ms-1s","1-5s","5-30s",">30s"]
allmod100=[]; allmod1=[]; rows=[]
for sl in slugs:
    ss=int(smap[sl]); se=ss+900_000_000
    for oc in ("Up","Down"):
        rec=bks.get((sl,oc))
        if rec is None or len(rec[0])<3: continue
        ts,ap,asz,bp,bs=rec
        ts=ts.astype(np.int64)
        # restrict to in-window snaps
        m=(ts>=ss)&(ts<=se); ts=ts[m]; ap=ap[m]; bp=bp[m]
        if len(ts)<3: continue
        span=(ts[-1]-ts[0])/1e6
        d=np.diff(ts)/1e6
        hist=np.histogram(d,bins=GB)[0]
        # book-moved across gaps >1s: best ask (min ask>0) / best bid (max bid>0)
        def best(P,row_i,side):
            r=P[row_i]; r=r[np.isfinite(r)&(r>0)]
            return (r.min() if side=="a" else r.max()) if r.size else np.nan
        big=np.where(d>1.0)[0]; moved=0
        for gi in big:
            a0=best(ap,gi,"a");a1=best(ap,gi+1,"a");b0=best(bp,gi,"b");b1=best(bp,gi+1,"b")
            if (np.isfinite(a0)and np.isfinite(a1)and abs(a0-a1)>1e-9) or (np.isfinite(b0)and np.isfinite(b1)and abs(b0-b1)>1e-9): moved+=1
        # mid-window stop: how far before slot_end does data END; and coverage = span/900
        end_gap=(se-ts[-1])/1e6; start_gap=(ts[0]-ss)/1e6
        allmod100.append(ts%100_000); allmod1.append(ts%1_000)
        rows.append(dict(slug=sl[-10:],oc=oc,n=len(ts),span=span,rate=len(ts)/max(span,1e-9),
            cover=span/900,start_gap=start_gap,end_gap=end_gap,maxgap=d.max(),p50=np.median(d),p90=np.percentile(d,90),
            nbig=len(big),moved=moved,**{GL[i]:hist[i] for i in range(len(GL))}))
R=pd.DataFrame(rows)
pd.set_option("display.width",200,"display.max_columns",40)
print("PER-SERIES (favorite=higher rate usually):")
print(R[["slug","oc","n","span","rate","cover","start_gap","end_gap","maxgap","p50","p90","nbig","moved"]].to_string(index=False))
print("\nGAP HISTOGRAM (summed across series):")
for g in GL: print(f"  {g:>10}: {int(R[g].sum()):>8,}")
print(f"\nMEDIAN snaps/sec (rate): {R['rate'].median():.1f}  | median coverage(span/900s): {R.cover.median():.2f}")
print(f"median end_gap (slot_end - last_snap): {R.end_gap.median():.0f}s  | median start_gap: {R.start_gap.median():.0f}s")
bigtot=R.nbig.sum(); movtot=R.moved.sum()
print(f">1s gaps: {int(bigtot):,}; book MOVED across {int(movtot):,} ({100*movtot/max(bigtot,1):.0f}%) = real missed data" )
# timestamp grid: 10Hz poller => ts concentrated at multiples of 100ms (mod 100000 ~ 0)
m100=np.concatenate(allmod100); m1=np.concatenate(allmod1)
print(f"\nTS GRID: ts%100ms: frac in [0,5ms]={np.mean(m100<5000):.2f} (high=>10Hz poller grid); ts%1ms: frac==0={np.mean(m1==0):.2f} (high=>ms-rounded)")
# how many series END early (data stop > 60s before slot_end while window active)
early=R[R.end_gap>60]
print(f"\nSERIES ENDING >60s EARLY (mid-window data stop): {len(early)}/{len(R)} ({100*len(early)/len(R):.0f}%)")
print(R.groupby("oc").agg(rate=("rate","median"),cover=("cover","median"),end_gap=("end_gap","median")).to_string())
