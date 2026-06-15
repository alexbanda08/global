"""Scrutinize the 5m stop result: decompose by won/lost, false-stop rate, book-fallback dependence."""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
c = pd.read_parquet(ROOT/"strategy_lab/directional/_results/scalp_hedge_physics_cache_2026_06_03.parquet")
c = c[(c.asset.isin(["BTC","ETH"]))&(c.filled==1)&(c.entry_vwap<0.55)].copy()
lf = pd.read_parquet(ROOT/"strategy_lab/lag_taker_fires_oos_2026_06_01.parquet")[["slug","direction"]].drop_duplicates("slug")
c = c.merge(lf,on="slug",how="left").dropna(subset=["direction"])
tk=lambda p:0.07*p*(1-p)
for tf in ["5m","15m"]:
    d=c[c.tf==tf].copy()
    rows=[]
    for _,r in d.iterrows():
        ev,sh,won=r.entry_vwap,r.shares,bool(r.won)
        b60raw=pd.to_numeric(pd.Series([r.bid_60]),errors="coerce").iloc[0]
        b60_missing=not np.isfinite(b60raw)
        b60=float(b60raw) if np.isfinite(b60raw) else (1.0 if won else 0.0)
        bids=[pd.to_numeric(pd.Series([r[f"bid_{k}"]]),errors="coerce").iloc[0] for k in [30,45,60]]
        bids=[x for x in bids if np.isfinite(x)]
        stop_lvl=ev-0.10
        hit=len(bids)>0 and min(bids)<=stop_lvl
        taker=(b60-ev)*sh-tk(b60)*sh
        stop=( (max(stop_lvl,0.01)-ev)*sh-tk(max(stop_lvl,0.01))*sh ) if hit else taker
        rows.append(dict(won=won,b60_missing=b60_missing,hit=hit,taker=taker,stop=stop,ev=ev,sh=sh,b60=b60))
    D=pd.DataFrame(rows)
    print(f"\n===== TF={tf}  n={len(D)} =====")
    print(f"  bid_60 missing (book-fallback used): {D.b60_missing.sum()}/{len(D)} ({100*D.b60_missing.mean():.1f}%)")
    print(f"  stop triggered: {D.hit.sum()}/{len(D)} ({100*D.hit.mean():.1f}%)")
    st=D[D.hit]
    print(f"    of stopped: won={st.won.sum()} lost={(~st.won).sum()}  (false-stops = stopped WINNERS)")
    # effect decomposition
    diff=D.stop-D.taker
    print(f"  total stop-taker: {diff.mean():+.4f}/tr  (sum {diff.sum():+.1f})")
    for grp,lab in [(D.won,"WINNERS"),(~D.won,"LOSERS")]:
        sub=diff[grp]; print(f"    {lab:8s} n={grp.sum():3d}  stop-taker={sub.mean():+.4f}/tr  sum={sub.sum():+.1f}")
    # how much of the LOSER benefit rides on book-fallback (b60=0) fires?
    los=D[~D.won]
    los_fb=los[los.b60_missing]; los_real=los[~los.b60_missing]
    print(f"    LOSERS w/ real book n={len(los_real)}: stop-taker={ (los_real.stop-los_real.taker).mean():+.4f}/tr")
    print(f"    LOSERS w/ fallback  n={len(los_fb)}: stop-taker={ (los_fb.stop-los_fb.taker).mean():+.4f}/tr (b60 forced 0 -> suspect)")
    # recompute stop benefit EXCLUDING fallback fires entirely
    Dr=D[~D.b60_missing]; dr=(Dr.stop-Dr.taker)
    def boot(v,nb=5000):
        v=np.asarray(v); i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
    lo,hi=boot(dr.values)
    print(f"  >> stop-taker EXCLUDING fallback fires: n={len(Dr)} {dr.mean():+.4f}/tr CI=[{lo:+.4f},{hi:+.4f}]")
