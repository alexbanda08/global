"""
momo_HOLD_f7 (v1) FULL backtest — BTC/ETH/SOL 15m, all local data (Apr22 -> Jun8), correct 0.07 fee.
Production-verified logic (confirmed vs vps3 2026-06-08): ws_s=slot_start-900; ret_2m=log(c@(ws_s+120)/c@ws_s);
fire@ws_s+120; gate |ret_2m|>=rolling-14d q90 (feed-backed, >=50 samples); F7 RSI14 simple-Wilder @ ws_s, UP>50/
DOWN<50; $25 L25 book-walk fill @ fire_us; HOLD to resolution. PRODUCTION HAS NO SPREAD FILTER -> spread_filter=1.0.
Fee = 0.07 winner-only (NOT legacy). Saves per-trade parquet for the rigor+live-compare step.
"""
from __future__ import annotations
import sys, math, gc
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT/"data"/"v4"/"canonical")); sys.path.insert(0, str(ROOT/"strategy_lab"))
from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming
from engine_v2 import LegacyConfig, fill_at_book

NOTIONAL=25.0; GATE_Q=0.90; LOOKBACK_DAYS=14; SLUG_BATCH=120
SPREAD_FILTER=1.0   # production momo has NO spread gate -> never reject
WIN_LO=int(pd.Timestamp("2026-04-22 00:00:00",tz="UTC").timestamp())  # slug suffix = slot_start in SECONDS
WIN_HI=int(pd.Timestamp("2026-06-08 23:59:00",tz="UTC").timestamp())
CFG=LegacyConfig()
OUT=ROOT/"strategy_lab/directional/_results"; OUT.mkdir(parents=True,exist_ok=True)

def asof_close(k,ts_s):
    eu,cl=k; i=int(np.searchsorted(eu,int(ts_s)*1_000_000,"right"))-1
    return float("nan") if i<0 else float(cl[i])
def ret_log(k,t0,t1):
    c0=asof_close(k,t0); c1=asof_close(k,t1)
    return float("nan") if not(math.isfinite(c0) and math.isfinite(c1) and c0>0 and c1>0) else math.log(c1/c0)
def rsi14_at(k,anchor_s):
    eu,cl=k; tgt=int(anchor_s)*1_000_000; i=int(np.searchsorted(eu,tgt,"right"))-1
    if i<14 or i>=len(cl) or abs(int(eu[i])-tgt)>5*60*1_000_000: return float("nan")
    d=np.diff(cl[i-14:i+1]); g=np.where(d>0,d,0.0).mean(); l=np.where(d<0,-d,0.0).mean()
    if l<=0: return 100.0 if g>0 else 50.0
    return float(100.0-100.0/(1.0+g/l))
def build_absret(k):
    eu,cl=k; ts=eu-60_000_000; lc=np.log(np.where(cl>0,cl,np.nan)); ar=np.full_like(lc,np.nan)
    ar[2:]=np.abs(lc[2:]-lc[:-2])
    dt=ts[2:]-ts[:-2]; ar[2:][dt!=120_000_000]=np.nan
    return ts,ar
def q90_asof(ts,ar,tgt_s):
    win=LOOKBACK_DAYS*24*3600*1_000_000; a=int(tgt_s)*1_000_000; v=np.isfinite(ar); vs=ts[v]; vv=ar[v]
    lo=int(np.searchsorted(vs,a-win,"left")); hi=int(np.searchsorted(vs,a,"right"))
    return float("nan") if hi-lo<50 else float(np.quantile(vv[lo:hi],GATE_Q))

print("[1] klines"); klines={}; feed={}
for a in ("BTC","ETH","SOL"):
    eu,cl=load_klines_asof(a,source="binance-spot-ws",period_id="1MIN")
    klines[a]=(eu.astype("int64"),cl.astype("float64")); feed[a]=build_absret(klines[a])
    print(f"   {a}: {len(eu)} bars -> {pd.Timestamp(int(eu[-1]),unit='us',tz='UTC')}")

print("[2] universe"); res=load_resolutions(assets=["BTC","ETH","SOL"],timeframes=["15m"])
res=res[res.outcome.isin(("Up","Down"))].copy()
res["slot_start"]=res.slug.str.extract(r"-(\d+)$")[0].astype("int64"); res["asset"]=res.ticker
res=res[(res.slot_start>=WIN_LO)&(res.slot_start<=WIN_HI)].sort_values("slot_start").reset_index(drop=True)
# FIX 2026-06-08: canonical slug suffix = window START = strike time (verified: strike_ts==suffix, settle==suffix+900).
# Live momo trades THIS window: ws_s = suffix (window start), fire = ws_s+120 (120s into the open window), resolve suffix+900.
# (The old harness used suffix-900 = PREVIOUS window -> fired 13min pre-open on a thin book + wrong-window momentum.)
res["ws_s"]=res.slot_start
print(f"   {len(res)} BTC/ETH/SOL 15m slots  {res.groupby('asset').size().to_dict()}")

print("[3] gated fires (v1 + F7)")
fires=[]
for r in res.itertuples(index=False):
    k=klines[r.asset]; ws=int(r.ws_s); ret=ret_log(k,ws,ws+120)
    if not math.isfinite(ret) or ret==0: continue
    thr=q90_asof(feed[r.asset][0],feed[r.asset][1],ws)
    if not math.isfinite(thr) or abs(ret)<thr: continue
    sig="UP" if ret>0 else "DOWN"; rsi=rsi14_at(k,ws)
    if not math.isfinite(rsi): continue
    if (sig=="UP" and rsi<=50) or (sig=="DOWN" and rsi>=50): continue
    fires.append(dict(slug=r.slug,asset=r.asset,slot_start=int(r.slot_start),ws_s=ws,
        fire_us=(ws+120)*1_000_000,signal=sig,outcome=r.outcome,ret_2m=float(ret),rsi=float(rsi),
        won=((sig=="UP" and r.outcome=="Up") or (sig=="DOWN" and r.outcome=="Down"))))
F=pd.DataFrame(fires); print(f"   gated fires: {len(F)}  {F.groupby('asset').size().to_dict()}")

print("[4] L25 fills (0.07 fee, no spread filter)")
rows=[]
for a in ("BTC","ETH","SOL"):
    sub=F[F.asset==a]; slugs=sorted(sub.slug.unique())
    for bi in range(0,len(slugs),SLUG_BATCH):
        batch=set(slugs[bi:bi+SLUG_BATCH])
        books=load_orderbook_l25_streaming(a.lower(),slugs=batch,subsample_1hz=False)
        for r in sub[sub.slug.isin(batch)].itertuples(index=False):
            oc="Up" if r.signal=="UP" else "Down"
            fill=fill_at_book(books,r.slug,oc,int(r.fire_us),cfg=CFG,notional_usd=NOTIONAL,spread_filter=SPREAD_FILTER)
            if fill is None: continue
            vw=float(fill["vwap"]); sh=NOTIONAL/vw; won=bool(r.won)
            pnl07=sh*(1-vw)*(1-0.07*vw) if won else -sh*vw
            rows.append(dict(sleeve_id=f"poly_updown_{a.lower()}_15m_momo_HOLD_f7",asset=a,slug=r.slug,
                fire_us=int(r.fire_us),signal=r.signal,outcome=r.outcome,won=won,entry_vwap=vw,
                ret_2m=r.ret_2m,rsi=r.rsi,pnl_07=pnl07))
        del books; gc.collect()
T=pd.DataFrame(rows); T.to_parquet(OUT/"momo_f7_bt_alltrades_CORRECTED_2026_06_08.parquet",index=False)
print(f"   filled: {len(T)}  saved -> momo_f7_bt_alltrades_CORRECTED_2026_06_08.parquet")

print("\n===== BACKTEST per sleeve (full window Apr22->Jun8, 0.07 fee, no spread filter) =====")
from scipy import stats
def boot(v,nb=5000):
    v=np.asarray(v); i=np.random.default_rng(42).integers(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
print(f"{'sleeve':<40}{'n':>5}{'WR%':>7}{'$/tr':>9}{'total':>10}{'vwap':>7}{'binomP':>9}  CI95")
for sid,g in T.groupby("sleeve_id"):
    n=len(g); wr=g.won.mean(); m=g.pnl_07.mean(); lo,hi=boot(g.pnl_07.values)
    bp=stats.binomtest(int(g.won.sum()),n,0.5,alternative="greater").pvalue
    print(f"{sid:<40}{n:>5}{100*wr:>7.1f}{m:>+9.3f}{g.pnl_07.sum():>+10.1f}{g.entry_vwap.mean():>7.3f}{bp:>9.5f}  [{lo:+.3f},{hi:+.3f}]")
