"""
08 — HEDGE_LATE parameter sweep on BTC sleeves (fresh L25).
HEDGE_LATE(frac, late_s): in the last `late_s` before resolution, if held-token bid < entry*frac
(bet clearly losing), SELL at bid. Cuts near-certain losers; risk = clipping a recovering winner.
Confirms whether the 07 finding (helps marginal sleeves, hurts winners) is robust across params.
"""
import sys, os, time
import numpy as np, pandas as pd
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT,"strategy_lab")); sys.path.insert(0, os.path.join(ROOT,"data/v4/canonical"))
from engine_v2 import find_book_strict, sell_at_bid_partial, LegacyConfig
from load import load_resolutions, load_orderbook_l25_streaming
OUTD=os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30"); cfg=LegacyConfig(); STALE=cfg.max_book_staleness_us
SEEDS=list(range(10)); TEMP=os.path.join(OUTD,"_results","btc_l25_topoff.parquet")
AP=[f"ask_price_{i}" for i in range(25)]; ASZ=[f"ask_size_{i}" for i in range(25)]
BP=[f"bid_price_{i}" for i in range(25)]; BSZ=[f"bid_size_{i}" for i in range(25)]
def sn(book,shares):
    if book is None: return None
    sv,ss,su=sell_at_bid_partial([float(x) for x in book["bp"]],[float(x) for x in book["bsz"]],shares)
    return sv if ss>0 else None
def bb(book):
    if book is None or not len(book.get("bp",[])): return None
    v=float(book["bp"][0]); return v if np.isfinite(v) and v>0 else None
def build_temp(slugs):
    df=pd.read_parquet(TEMP, columns=["timestamp_us","slug","outcome"]+AP+ASZ+BP+BSZ)
    df=df[df.slug.isin(slugs)]; books={}
    for (s,o),g in df.groupby(["slug","outcome"]):
        g=g.sort_values("timestamp_us")
        books[(s,o)]=(g.timestamp_us.values.astype(np.int64),g[AP].values.astype(float),
                      g[ASZ].values.astype(float),g[BP].values.astype(float),g[BSZ].values.astype(float))
    return books
def cilo(d):
    d=np.asarray(d,float); d=d[~np.isnan(d)]
    if len(d)<10: return np.nan
    return float(np.median([np.percentile(d[np.random.default_rng(s).integers(0,len(d),(2000,len(d)))].mean(1),2.5) for s in SEEDS]))

fr=pd.read_parquet(os.path.join(OUTD,"_results","fires_resolved_all.parquet"))
res=load_resolutions()
sub=fr[(fr.asset=="BTC")&(fr.fire_us.notna())&(fr.fire_offset_s.notna())].copy()
sub["slot_start_us"]=sub.slug.astype(str).str.rsplit("-",n=1).str[-1].astype(np.int64)*1_000_000
sub["entry_us"]=sub.slot_start_us+sub.fire_offset_s.astype(np.int64)*1_000_000
sub["end_us"]=sub.fire_us.astype(np.int64); sub=sub[sub.end_us>sub.entry_us]
slugs=set(sub.slug); temp=build_temp(slugs); need=set(s for (s,o) in temp.keys())
canon=load_orderbook_l25_streaming("btc",slugs=slugs-need,subsample_1hz=False) if (slugs-need) else {}
books={**canon,**temp}
print(f"books {len(books)} pairs")

FRACS=[0.55,0.65,0.75]; LATES=[30,45,60,90]
SLEEVES=["btc_5m_parent15m_notrang_ts_mpskew_v7","btc_15m_vwapprem_ema50_mpskew_off600_v6",
         "btc_15m_ema50_ema800_off600_down","btc_5m_l_1hrf_imb5_ribbon_v8",
         "btc_5m_q_parent15mslope_ts_imb5_v8","btc_5m_ts_mpskew_any_off30"]
rows=[]
for sl in SLEEVES:
    g=sub[sub.sleeve==sl].sort_values("at")
    if len(g)<20: continue
    # precompute bid path per fire once
    paths=[]
    for _,r in g.iterrows():
        oc="Up" if r.direction=="UP" else "Down"; entry=float(r.entry_vwap); shares=float(r.shares)
        if not (entry>0 and shares>0): continue
        rec=books.get((r.slug,oc)); seq=[]
        if rec is not None:
            ts=rec[0]; lo=np.searchsorted(ts,int(r.entry_us),side="right"); hi=np.searchsorted(ts,int(r.end_us),side="right")
            for t in ts[lo:hi]:
                bk=find_book_strict(books,r.slug,oc,int(t),max_staleness_us=STALE); v=bb(bk)
                if v is not None: seq.append((int(t),v,bk))
        paths.append(dict(entry=entry,shares=shares,hold=float(r.pnl_usd),end=int(r.end_us),seq=seq))
    base=sum(p["hold"] for p in paths); mid=len(paths)//2
    for frac in FRACS:
        for late in LATES:
            deltas=[]
            for p in paths:
                pnl=p["hold"]
                for (t,b,bk) in p["seq"]:
                    if t>=p["end"]-late*1_000_000 and b<p["entry"]*frac:
                        sv=sn(bk,p["shares"]);
                        if sv is not None: pnl=p["shares"]*(sv-p["entry"])
                        break
                deltas.append(pnl-p["hold"])
            deltas=np.array(deltas); cl=cilo(deltas)
            d1=deltas[:mid].mean(); d2=deltas[mid:].mean()
            rows.append(dict(sleeve=sl,n=len(paths),frac=frac,late_s=late,base_total=round(base,1),
                delta_total=round(deltas.sum(),1),delta_mean=round(deltas.mean(),4),
                cilo=round(cl,4) if cl==cl else None,wf_h1=round(d1,4),wf_h2=round(d2,4),
                beats=bool(deltas.mean()>0 and cl==cl and cl>0 and d1>0 and d2>0)))
out=pd.DataFrame(rows); out.to_csv(os.path.join(OUTD,"_results","hedge_late_sweep.csv"),index=False)
pd.set_option("display.width",200)
for sl in SLEEVES:
    s=out[out.sleeve==sl]
    if len(s)==0: continue
    base=s.base_total.iloc[0]
    print(f"\n## {sl}  base_total ${base} (n={s.n.iloc[0]})  [HEDGE_LATE frac x late_s]")
    print(s[["frac","late_s","delta_total","delta_mean","cilo","wf_h1","wf_h2","beats"]].to_string(index=False))
print("\nWROTE _results/hedge_late_sweep.csv")
