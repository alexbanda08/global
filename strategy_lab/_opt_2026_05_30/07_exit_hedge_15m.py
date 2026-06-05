"""
07 — Exit/hedge re-run on BTC with FRESH L25 (canonical + May29-31 top-off overlay).
Covers the previously-uncovered recent BTC fires incl. the 15m sleeves.
Same policy grid + oracle-confirmed reversal cut/lock as 06, 10-seed bootstrap + walk-forward.
"""
import sys, os, time
import numpy as np, pandas as pd
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT,"strategy_lab"))
sys.path.insert(0, os.path.join(ROOT,"data/v4/canonical"))
from engine_v2 import find_book_strict, sell_at_bid_partial, LegacyConfig
from load import load_resolutions, load_orderbook_l25_streaming, load_chainlink_rtds
OUTD=os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30")
cfg=LegacyConfig(); STALE=cfg.max_book_staleness_us; SEEDS=list(range(10))
TEMP=os.path.join(OUTD,"_results","btc_l25_topoff.parquet")
AP=[f"ask_price_{i}" for i in range(25)]; ASZ=[f"ask_size_{i}" for i in range(25)]
BP=[f"bid_price_{i}" for i in range(25)]; BSZ=[f"bid_size_{i}" for i in range(25)]

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
    sv,ss,su=sell_at_bid_partial(bp,bs,shares); return sv if ss>0 else None
def cl_asof(ts,px,t):
    i=np.searchsorted(ts,t,side="right")-1; return float(px[i]) if i>=0 else None

def build_temp_books(slugs):
    df=pd.read_parquet(TEMP, columns=["timestamp_us","slug","outcome"]+AP+ASZ+BP+BSZ)
    df=df[df.slug.isin(slugs)]
    books={}
    for (slug,oc),g in df.groupby(["slug","outcome"]):
        g=g.sort_values("timestamp_us")
        books[(slug,oc)]=(g.timestamp_us.values.astype(np.int64),
                          g[AP].values.astype(float), g[ASZ].values.astype(float),
                          g[BP].values.astype(float), g[BSZ].values.astype(float))
    return books

def run(sub, books, cl_ts, cl_px):
    recs=[]
    for _,r in sub.iterrows():
        slug=r.slug; direction=r.direction
        oc="Up" if direction=="UP" else "Down"; opp="Down" if oc=="Up" else "Up"
        entry_us=int(r.entry_us); end_us=int(r.end_us)
        entry=float(r.entry_vwap) if pd.notna(r.entry_vwap) else None
        shares=float(r.shares) if pd.notna(r.shares) else None
        hold=float(r.pnl_usd); strike=r.strike_price
        if entry is None or shares is None or entry<=0: continue
        rec=books.get((slug,oc)); snaps=np.array([],dtype=np.int64)
        if rec is not None:
            ts=rec[0]; lo=np.searchsorted(ts,entry_us,side="right"); hi=np.searchsorted(ts,end_us,side="right"); snaps=ts[lo:hi]
        row=dict(slug=slug, sleeve=r.sleeve, direction=direction, won=bool(r.won),
                 entry=entry, shares=shares, hold=hold, hold_s=(end_us-entry_us)/1e6,
                 n_snaps=len(snaps), at_ts=pd.Timestamp(r["at"]).value)
        bids=[]
        for ts_ in snaps:
            b=find_book_strict(books,slug,oc,int(ts_),max_staleness_us=STALE); bb=best_bid(b)
            if bb is not None: bids.append((int(ts_),bb,b))
        def first_sell(cond):
            for (t,b,bk) in bids:
                if cond(t,b):
                    sv=sell_now(bk,shares)
                    if sv is not None: return shares*(sv-entry)
            return hold
        for th in [0.30,0.40,0.50]: row[f"SL_{th}"]=first_sell(lambda t,b,th=th: b<=th)
        for th in [0.90,0.95,0.97]: row[f"TP_{th}"]=first_sell(lambda t,b,th=th: b>=th)
        for dd in [0.10,0.15]:
            peak=-1; pnl=hold
            for (t,b,bk) in bids:
                peak=max(peak,b)
                if b<=peak-dd:
                    sv=sell_now(bk,shares); pnl=shares*(sv-entry) if sv is not None else hold; break
            row[f"TRAIL_{dd}"]=pnl
        row["HEDGE_LATE"]=first_sell(lambda t,b: (t>=end_us-30_000_000) and (b<entry*0.7))
        for mbps in [0.0,2.0,5.0]:
            pnl=hold
            if strike is not None and np.isfinite(strike):
                marg=strike*mbps/1e4
                for (t,b,bk) in bids:
                    clp=cl_asof(cl_ts,cl_px,t)
                    if clp is None: continue
                    if (clp<strike-marg) if direction=="UP" else (clp>strike+marg):
                        sv=sell_now(bk,shares); pnl=shares*(sv-entry) if sv is not None else hold; break
            row[f"ORACLE_CUT_{mbps}"]=pnl
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
                            pnl=shares*1.0 - shares*entry - shares*float(ob["ap"][0])
                        break
            row[f"ORACLE_LOCK_{mbps}"]=pnl
        recs.append(row)
    return pd.DataFrame(recs)

def boot_cilo(d):
    d=np.asarray(d,float); d=d[~np.isnan(d)]
    if len(d)<10: return np.nan
    los=[]
    for s in SEEDS:
        rng=np.random.default_rng(s); idx=rng.integers(0,len(d),size=(2000,len(d)))
        los.append(np.percentile(d[idx].mean(axis=1),2.5))
    return float(np.median(los))

def summarize(df,label):
    skip=("slug","sleeve","direction","won","entry","shares","hold","hold_s","n_snaps","at_ts")
    pols=[c for c in df.columns if c not in skip]; df=df.sort_values("at_ts"); mid=len(df)//2
    base=df.hold.sum(); out=[]
    for p in pols:
        d=df[p]-df.hold; cilo=boot_cilo(d.values)
        d1=(df.iloc[:mid][p]-df.iloc[:mid].hold).mean(); d2=(df.iloc[mid:][p]-df.iloc[mid:].hold).mean()
        out.append(dict(policy=p,n=len(df),delta_total=round(d.sum(),1),delta_mean=round(d.mean(),4),
            cilo=round(cilo,4) if cilo==cilo else None,wf_h1=round(d1,4),wf_h2=round(d2,4),
            beats=(d.mean()>0 and cilo is not None and cilo>0 and d1>0 and d2>0),
            pct=round(100*(df[p]!=df.hold).mean(),1)))
    res=pd.DataFrame(out).sort_values("delta_total",ascending=False)
    cov=(df.n_snaps>0).mean()*100
    print(f"\n=== {label}  n={len(df)} | HOLD ${base:.1f} mean ${df.hold.mean():.3f} | book-cov {cov:.0f}% | med hold {df.hold_s.median():.0f}s ===")
    print(res.to_string(index=False))
    return res

def main():
    fr=pd.read_parquet(os.path.join(OUTD,"_results","fires_resolved_all.parquet"))
    res=load_resolutions()
    d=load_chainlink_rtds("BTC").sort_values("timestamp_us")
    cl_ts=d["timestamp_us"].values.astype(np.int64); cl_px=d["price_value"].values.astype(float)
    sub=fr[(fr.asset=="BTC")&(fr.fire_us.notna())&(fr.fire_offset_s.notna())].copy()
    sub["slot_start_us"]=sub.slug.astype(str).str.rsplit("-",n=1).str[-1].astype(np.int64)*1_000_000
    sub["entry_us"]=sub.slot_start_us+(sub.fire_offset_s.astype(np.int64))*1_000_000
    sub["end_us"]=sub.fire_us.astype(np.int64)
    sub=sub[sub.end_us>sub.entry_us]
    sub=sub.merge(res[["slug","strike_price"]].drop_duplicates("slug"),on="slug",how="left")
    slugs=set(sub.slug)
    t0=time.time(); temp=build_temp_books(slugs); print(f"temp books {len(temp)} pairs {time.time()-t0:.0f}s")
    need=set(s for (s,o) in temp.keys())
    canon_slugs=slugs-need
    canon=load_orderbook_l25_streaming("btc",slugs=canon_slugs,subsample_1hz=False) if canon_slugs else {}
    books={**canon,**temp}; print(f"merged books {len(books)} pairs (canon {len(canon)} + temp {len(temp)})")
    df=run(sub,books,cl_ts,cl_px)
    df.to_parquet(os.path.join(OUTD,"_results","exit_grid_BTC_fresh.parquet"),index=False)
    summarize(df,"BTC ALL (fresh L25)")
    for sl in ["btc_15m_ema50_ema800_off600_down","btc_15m_vwapprem_ema50_mpskew_off600_v6",
               "btc_5m_l_1hrf_imb5_ribbon_v8","btc_5m_q_parent15mslope_ts_imb5_v8",
               "btc_5m_parent15m_notrang_ts_mpskew_v7"]:
        sd=df[df.sleeve==sl]
        if len(sd)>=20: summarize(sd,sl)
    # 15m pooled
    m15=df[df.sleeve.str.startswith("btc_15m")]
    if len(m15)>=20: summarize(m15,"BTC 15m POOLED")
    print("\nDONE")

if __name__=="__main__": main()
