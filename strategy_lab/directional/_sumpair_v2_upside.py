"""V2 oscillation-harvest UPSIDE number — bounds the edge between 1-clip (+$0.52) and unlimited (+$2.24)
by (1) sweeping a max-clips-per-side cap and (2) replacing the level-0 size==0->DEEP fill (infinite refill,
the headline inflation) with a REAL 25-level depth walk. 5m only (the edge is 5m). HANG-PROOF: every loop
has a hard iteration cap. Reuses validated helpers from _sumpair_signal_oscillation_harvest.
"""
import sys, os, time, importlib.util
sys.path.insert(0, "data/v4/canonical"); sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd

_p = os.path.join(os.path.dirname(__file__), "_sumpair_signal_oscillation_harvest.py")
spec = importlib.util.spec_from_file_location("osc", _p); OSC = importlib.util.module_from_spec(spec); spec.loader.exec_module(OSC)
# reuse validated constants + helpers
asof_on = OSC.asof_on; pair_locked_pnl = OSC.pair_locked_pnl; held_value = OSC.held_value
entry_fill = OSC.entry_fill; exit_fill = OSC.exit_fill
CLIP=OSC.CLIP_STAKE; SPREAD=OSC.SPREAD; VG=OSC.VWAP_GATE; LAT=OSC.LAT_US; STEP=OSC.GRID_STEP_US
DLB=OSC.DELTA_LOOKBACK_US; TAIL=OSC.TAIL_PAD_US; FEE=OSC.FEE
THR=3.0; MAXCLIPS=[1,2,3,4,6,8,999]; IS_CUT=int(pd.Timestamp("2026-05-21",tz="UTC").timestamp()*1e6)
MAX_ITER=400  # hard guard: 15m window / 5s = 180 steps; 400 is a safe ceiling -> can NEVER hang

def realdepth_fill(ap_row, asz_row, stake):
    """Walk the full 25-level ask ladder with REAL sizes (size==0 => 0 at that level, NOT deep).
    Returns (shares, vwap, fillable_usd) for up to `stake` $; partial if depth insufficient."""
    rem = stake; sh = 0.0; cost = 0.0
    for lv in range(ap_row.shape[0]):
        p = ap_row[lv]; s = asz_row[lv]
        if not np.isfinite(p) or p <= 0: break
        if not np.isfinite(s) or s <= 0: continue   # real: no liquidity at this level (NOT deep)
        take_usd = min(rem, s * p)
        q = take_usd / p
        sh += q; cost += q * p; rem -= take_usd
        if rem <= 1e-9: break
    if sh <= 0: return None
    return dict(shares=sh, ev=cost / sh, filled_usd=cost)

def harvest_capped(ends, close, rec_up, rec_dn, ss, se, outcome, max_clip, real_depth):
    won={"Up":outcome=="Up","Down":outcome=="Down"}; recs={"Up":rec_up,"Down":rec_dn}
    sh={"Up":0.,"Down":0.}; cost={"Up":0.,"Down":0.}; nclip={"Up":0,"Down":0}
    depth_short={"Up":0,"Down":0}  # times real depth couldn't fill a full clip
    t=ss+5_000_000; t_stop=se-TAIL; it=0
    while t<=t_stop and it<MAX_ITER:
        it+=1
        pn=asof_on(ends,close,t); pp=asof_on(ends,close,t-DLB)
        if np.isfinite(pn) and np.isfinite(pp) and pp>0:
            d=abs(pn/pp-1.0)*1e4
            if d>=THR:
                side="Up" if pn/pp-1.0>0 else "Down"; rec=recs[side]
                if rec is not None and nclip[side]<max_clip:
                    ts,ap,asz,bp,bsz=rec
                    j=int(np.searchsorted(ts,t+LAT,"right"))-1
                    if j>=0:
                        if real_depth:
                            ent=realdepth_fill(ap[j],asz[j],CLIP)
                            if ent is not None and ent["filled_usd"]<CLIP-0.01: depth_short[side]+=1
                        else:
                            ent=entry_fill(ts,ap[:,0],asz[:,0],t+LAT,CLIP,SPREAD,bp[:,0])
                        if ent is not None and ent["ev"]<VG:
                            sh[side]+=ent["shares"]; cost[side]+=ent["shares"]*ent["ev"]; nclip[side]+=1
        t+=STEP
    ev={s:(cost[s]/sh[s]) if sh[s]>0 else np.nan for s in("Up","Down")}
    m=min(sh["Up"],sh["Down"])
    if m>0:
        pw,pl=(ev["Up"],ev["Down"]) if won["Up"] else (ev["Down"],ev["Up"])
        locked=pair_locked_pnl(m,pw,pl); paircost=ev["Up"]+ev["Down"]
    else: locked=0.; paircost=np.nan
    resid=held_value(sh["Up"]-m,ev["Up"],won["Up"])+held_value(sh["Down"]-m,ev["Down"],won["Down"])
    return dict(net=locked+resid, locked=locked, resid=resid, matched=m, paircost=paircost,
                nclip_up=nclip["Up"], nclip_dn=nclip["Down"], both=(sh["Up"]>0 and sh["Down"]>0),
                depth_short=depth_short["Up"]+depth_short["Down"])

def boot(v,nb=3000):
    v=np.asarray(v,float); v=v[~np.isnan(v)]
    if len(v)<5: return (np.nan,np.nan)
    rng=np.random.default_rng(0); bs=rng.choice(v,(nb,len(v)),replace=True).mean(1)
    return tuple(np.percentile(bs,[2.5,97.5]))

def main():
    t0=time.time(); print("V2 UPSIDE — max-clip sweep + real-depth fill (5m)",flush=True)
    res=OSC.load_resolutions(); res=res[res.timeframe=="5m"].drop_duplicates("slug")
    res=res[res.ticker.isin(["BTC","ETH","SOL"])]
    print(f"5m slugs {len(res)}",flush=True)
    rows=[]
    for coin in ["BTC","ETH","SOL"]:
        d=res[res.ticker==coin]
        if len(d)==0: continue
        _,ends,close=OSC.unified_1s(coin)
        slugs=sorted(d.slug)[::10]; CH=200   # 1/10 stride: aggregate curve still tight, box is contended
        slot_map=dict(zip(d.slug,d.slot_start_us)); out_map=dict(zip(d.slug,d.outcome))
        for i in range(0,len(slugs),CH):
            ch=slugs[i:i+CH]
            bks=OSC.load_orderbook_l25_streaming(coin.lower(),slugs=set(ch),subsample_1hz=False)
            for sl in ch:
                ss=int(slot_map[sl]); se=ss+300_000_000; oc=out_map[sl]
                ru=bks.get((sl,"Up")); rd=bks.get((sl,"Down"))
                if ru is None or rd is None: continue
                for mc in MAXCLIPS:
                    for rd_flag in (False,True):
                        r=harvest_capped(ends,close,ru,rd,ss,se,oc,mc,rd_flag)
                        r.update(slug=sl,coin=coin,max_clip=mc,real_depth=rd_flag,
                                 oos=ss>=IS_CUT,fired=(r["nclip_up"]+r["nclip_dn"])>0)
                        rows.append(r)
            print(f"  {coin} {i+len(ch)}/{len(slugs)} t={time.time()-t0:.0f}s",flush=True)
    R=pd.DataFrame(rows); R.to_parquet(os.path.join(os.path.dirname(__file__),"_results","sumpair_v2_upside_2026_06_15.parquet"),index=False)
    print(f"\nsaved {len(R)} rows t={time.time()-t0:.0f}s\n"+"="*70,flush=True)
    print("UPSIDE CURVE — net/slug (fired) vs max_clip, OOS, THR=3"); print("="*70)
    for rd_flag in (False,True):
        tag="REAL-DEPTH" if rd_flag else "level0(size==0->DEEP, V2-headline fill)"
        print(f"\n--- fill model: {tag} ---")
        for mc in MAXCLIPS:
            g=R[(R.max_clip==mc)&(R.real_depth==rd_flag)&(R.oos)&(R.fired)]
            if len(g)==0: print(f"  max_clip={mc}: (none)"); continue
            net=g.net.to_numpy(); lo,hi=boot(net)
            bothpct=100*g.both.mean(); dshort=g.depth_short.mean() if rd_flag else 0
            print(f"  max_clip={str(mc):>3}: n={len(g):4d} net/slug={net.mean():+.3f} CI[{lo:+.3f},{hi:+.3f}] "
                  f"med={np.median(net):+.3f} %pos={100*(net>0).mean():.0f}% both%={bothpct:.0f}%"
                  + (f" depth_short/slug={dshort:.1f}" if rd_flag else ""))
    # how many clips does real depth actually support (unlimited-cap, real-depth run)
    g=R[(R.max_clip==999)&(R.real_depth)&(R.oos)&(R.fired)]
    if len(g):
        tot=(g.nclip_up+g.nclip_dn)
        print(f"\nREAL-DEPTH clips/side supported (max_clip=inf): median={tot.median():.0f} "
              f"p25={tot.quantile(.25):.0f} p75={tot.quantile(.75):.0f} p95={tot.quantile(.95):.0f}")
    print(f"\ntotal t={time.time()-t0:.0f}s")

if __name__=="__main__": main()
