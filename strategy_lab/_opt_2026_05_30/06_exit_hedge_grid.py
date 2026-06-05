"""
06 (v2) — Exit/Hedge policy grid over the REAL holding window.
CORRECTED TIMING: entry_us = slot_start_us + fire_offset_s*1e6 ; slot_end_us = fire_us (resolution).
True hold = window - offset = 1..5 minutes (NOT 20s). Exit/hedge therefore CAN act.

Entry = real logged fill (entry_vwap, shares). HOLD = logged pnl_usd (0.07-curve fee, real).
Early-SELL PnL = shares*(sell_vwap - entry)  [no resolution fee — closed early; this is REAL,
and legitimately lets TP avoid the win-fee]. HEDGE-LOCK buys opposite token at ask.

Tests: SL, TP, TRAIL, HEDGE_LATE, and the novel ORACLE-CONFIRMED REVERSAL CUT/LOCK
(chainlink RTDS vs strike — the actual settlement oracle).
Validation: per-fire paired delta vs HOLD; 10-seed bootstrap CI-lo; chronological walk-forward.
Assets: BTC + ETH (dense L25). SOL excluded (ask-side 55% NaN).
"""
import sys, os, time
import numpy as np, pandas as pd
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT,"strategy_lab"))
sys.path.insert(0, os.path.join(ROOT,"data/v4/canonical"))
from engine_v2 import find_book_strict, sell_at_bid_partial, LegacyConfig
from load import load_resolutions, load_orderbook_l25_streaming, load_chainlink_rtds

OUTD=os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30")
cfg=LegacyConfig(); STALE=cfg.max_book_staleness_us
SAMPLE_PER_ASSET=700
SEEDS=list(range(10))

def best_bid(book):
    if book is None: return None
    bp=book.get("bp")
    if bp is None or len(bp)==0: return None
    try:
        v=float(bp[0]); return v if np.isfinite(v) and v>0 else None
    except: return None

def sell_now(book, shares):
    if book is None: return None
    bp=[float(x) for x in book["bp"]]; bs=[float(x) for x in book["bsz"]]
    sv,ss,su=sell_at_bid_partial(bp,bs,shares)
    return sv if ss>0 else None

def cl_asof(ts_arr, px_arr, target_us):
    i=np.searchsorted(ts_arr, target_us, side="right")-1
    return float(px_arr[i]) if i>=0 else None

def load_asset(asset, fr, res):
    sub=fr[(fr.asset==asset)&(fr.fire_us.notna())&(fr.fire_offset_s.notna())].copy()
    sub["slot_start_us"]=sub.slug.astype(str).str.rsplit("-",n=1).str[-1].astype(np.int64)*1_000_000
    sub["entry_us"]=sub.slot_start_us + (sub.fire_offset_s.astype(np.int64))*1_000_000
    sub["end_us"]=sub.fire_us.astype(np.int64)   # fire_us == slot_end (resolution)
    sub=sub[sub.end_us>sub.entry_us]
    if len(sub)>SAMPLE_PER_ASSET:
        sub=sub.sample(SAMPLE_PER_ASSET, random_state=7)
    sub=sub.merge(res[["slug","strike_price"]].drop_duplicates("slug"), on="slug", how="left")
    slugs=set(sub.slug)
    mn=int(sub.entry_us.min())-5_000_000; mx=int(sub.end_us.max())+5_000_000
    t0=time.time()
    books=load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False,
                                       min_ts_us=mn, max_ts_us=mx)
    print(f"  [{asset}] {len(sub)} fires, {len(slugs)} slugs, L25 {len(books)} pairs, {time.time()-t0:.0f}s")
    return sub, books

def run_asset(asset, sub, books, cl_ts, cl_px):
    recs=[]
    for _,r in sub.iterrows():
        slug=r.slug; direction=r.direction
        oc="Up" if direction=="UP" else "Down"; opp="Down" if oc=="Up" else "Up"
        entry_us=int(r.entry_us); end_us=int(r.end_us)
        entry=float(r.entry_vwap) if pd.notna(r.entry_vwap) else None
        shares=float(r.shares) if pd.notna(r.shares) else None
        hold=float(r.pnl_usd); strike=r.strike_price
        if entry is None or shares is None or entry<=0: continue
        rec=books.get((slug,oc))
        snaps=np.array([],dtype=np.int64)
        if rec is not None:
            ts=rec[0]
            lo=np.searchsorted(ts,entry_us,side="right"); hi=np.searchsorted(ts,end_us,side="right")
            snaps=ts[lo:hi]
        row=dict(slug=slug, asset=asset, sleeve=r["sleeve"], direction=direction, won=bool(r["won"]),
                 entry=entry, shares=shares, hold=hold, hold_s=(end_us-entry_us)/1e6,
                 n_snaps=len(snaps), at_ts=pd.Timestamp(r["at"]).value)
        bids=[]
        for ts_ in snaps:
            b=find_book_strict(books,slug,oc,int(ts_),max_staleness_us=STALE)
            bb=best_bid(b)
            if bb is not None: bids.append((int(ts_),bb,b))
        def first_sell(cond):
            for (t,b,bk) in bids:
                if cond(t,b):
                    sv=sell_now(bk,shares)
                    if sv is not None: return shares*(sv-entry)
            return hold
        for th in [0.25,0.30,0.35,0.40,0.50]:
            row[f"SL_{th}"]=first_sell(lambda t,b,th=th: b<=th)
        for th in [0.85,0.90,0.95,0.97]:
            row[f"TP_{th}"]=first_sell(lambda t,b,th=th: b>=th)
        for dd in [0.10,0.15,0.20]:
            peak=-1; pnl=hold
            for (t,b,bk) in bids:
                peak=max(peak,b)
                if b<=peak-dd:
                    sv=sell_now(bk,shares)
                    if sv is not None: pnl=shares*(sv-entry)
                    break
            row[f"TRAIL_{dd}"]=pnl
        row["HEDGE_LATE"]=first_sell(lambda t,b: (t>=end_us-30_000_000) and (b<entry*0.7))
        # ORACLE-CONFIRMED REVERSAL CUT (sell) — chainlink crosses strike against bet
        for mbps in [0.0,2.0,5.0]:
            pnl=hold
            if strike is not None and np.isfinite(strike):
                marg=strike*mbps/1e4
                for (t,b,bk) in bids:
                    clp=cl_asof(cl_ts,cl_px,t)
                    if clp is None: continue
                    if (clp<strike-marg) if direction=="UP" else (clp>strike+marg):
                        sv=sell_now(bk,shares)
                        if sv is not None: pnl=shares*(sv-entry)
                        break
            row[f"ORACLE_CUT_{mbps}"]=pnl
        # ORACLE-CONFIRMED LOCK (buy opposite token at ask on reversal)
        for mbps in [0.0,2.0]:
            pnl=hold
            if strike is not None and np.isfinite(strike):
                marg=strike*mbps/1e4
                for (t,b,bk) in bids:
                    clp=cl_asof(cl_ts,cl_px,t)
                    if clp is None: continue
                    if (clp<strike-marg) if direction=="UP" else (clp>strike+marg):
                        ob=find_book_strict(books,slug,opp,int(t),max_staleness_us=STALE)
                        if ob is not None and len(ob["ap"]) and np.isfinite(ob["ap"][0]) and float(ob["ap"][0])>0:
                            opp_ask=float(ob["ap"][0])
                            pnl=shares*1.0 - shares*entry - shares*opp_ask  # locked min payoff
                        break
            row[f"ORACLE_LOCK_{mbps}"]=pnl
        recs.append(row)
    return pd.DataFrame(recs)

def boot_cilo(delta):
    delta=np.asarray(delta,float); delta=delta[~np.isnan(delta)]
    if len(delta)<10: return np.nan
    los=[]
    for s in SEEDS:
        rng=np.random.default_rng(s)
        idx=rng.integers(0,len(delta),size=(2000,len(delta)))
        los.append(np.percentile(delta[idx].mean(axis=1),2.5))
    return float(np.median(los))

def summarize(df, label):
    skip=("slug","asset","sleeve","direction","won","entry","shares","hold","hold_s","n_snaps","at_ts")
    pols=[c for c in df.columns if c not in skip]
    df=df.sort_values("at_ts"); mid=len(df)//2
    base_total=df.hold.sum(); base_mean=df.hold.mean()
    out=[]
    for p in pols:
        d=(df[p]-df.hold)
        cilo=boot_cilo(d.values)
        d1=(df.iloc[:mid][p]-df.iloc[:mid].hold).mean(); d2=(df.iloc[mid:][p]-df.iloc[mid:].hold).mean()
        out.append(dict(policy=p, n=len(df), pol_total=round(df[p].sum(),1),
            delta_total=round(d.sum(),1), delta_mean=round(d.mean(),4),
            cilo_delta=round(cilo,4) if cilo==cilo else None,
            wf_h1=round(d1,4), wf_h2=round(d2,4),
            beats=(d.mean()>0 and cilo is not None and cilo>0 and d1>0 and d2>0),
            pct_trig=round(100*(df[p]!=df.hold).mean(),1)))
    res=pd.DataFrame(out).sort_values("delta_total",ascending=False)
    print(f"\n=== {label}  n={len(df)} | HOLD total ${base_total:.1f} mean ${base_mean:.3f} | med hold {df.hold_s.median():.0f}s ===")
    print(res.to_string(index=False))
    return res

def main():
    fr=pd.read_parquet(os.path.join(OUTD,"_results","fires_resolved_all.parquet"))
    res=load_resolutions()
    rtds={}
    for a in ["BTC","ETH"]:
        d=load_chainlink_rtds(a).sort_values("timestamp_us")
        rtds[a]=(d["timestamp_us"].values.astype(np.int64), d["price_value"].values.astype(float))
    allres=[]
    for asset in ["BTC","ETH"]:
        sub,books=load_asset(asset,fr,res)
        cl_ts,cl_px=rtds[asset]
        df=run_asset(asset,sub,books,cl_ts,cl_px)
        df.to_parquet(os.path.join(OUTD,"_results",f"exit_grid_{asset}.parquet"),index=False)
        r=summarize(df,f"{asset} pooled"); r["asset"]=asset; allres.append(r)
        # also per top sleeve
        for sl in df.sleeve.value_counts().head(4).index:
            sd=df[df.sleeve==sl]
            if len(sd)>=40: summarize(sd, f"{asset}:{sl}")
    pd.concat(allres).to_csv(os.path.join(OUTD,"_results","exit_hedge_grid.csv"),index=False)
    print("\nWROTE _results/exit_hedge_grid.csv")

if __name__=="__main__":
    main()
