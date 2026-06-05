"""Refine exits: TP-or-time combos + trailing stop, off the cache. Deployed cell, fee 0.015 & 0.07."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
c = pd.read_parquet(ROOT/"strategy_lab"/"directional"/"_results"/"scalp_hedge_physics_cache_2026_06_03.parquet")
RNG=np.random.default_rng(3)
DTS=[30,45,60,75,90,120,150,180]
def boot(x,n=8000):
    x=np.asarray(x,float);x=x[np.isfinite(x)]
    if len(x)<3:return(np.nan,np.nan)
    m=x[RNG.integers(0,len(x),size=(n,len(x)))].mean(1);return float(np.percentile(m,2.5)),float(np.percentile(m,97.5))
def t(x):
    x=np.asarray(x,float);x=x[np.isfinite(x)];return np.nan if len(x)<3 or x.std(ddof=1)==0 else x.mean()/(x.std(ddof=1)/np.sqrt(len(x)))
def hold07(ev,sh,won):return sh*(1-ev)*(1-0.07*ev) if won else -sh*ev
def pnl(ev,sh,b,won,fee):
    if not np.isfinite(b):return hold07(ev,sh,won)
    return (b-ev)*sh-fee*sh*(ev*(1-ev)+b*(1-b))
def rpt(name,d,exitfn,fee=0.015):
    p=np.array([pnl(r.entry_vwap,r.shares,exitfn(r),r.won,fee) for r in d.itertuples()]);p=p[np.isfinite(p)]
    ci=boot(p);print(f"  {name:32} n={len(p):3} $/tr={p.mean():+6.2f} t={t(p):4.1f} CI[{ci[0]:+.2f},{ci[1]:+.2f}]")
F=c[c.filled]; D=F[(F.asset.isin(['BTC','ETH']))&(F.delta_bps>=5)&(F.entry_vwap<0.55)]
print(f"deployed cell n={len(D)}  (fee=0.015 unless noted)")
# baseline
rpt("TIME+60",D,lambda r:r.bid_60)
rpt("TIME+45",D,lambda r:r.bid_45)
# TP-or-time: sell at TP price if hit before T, else bid at T
def tp_or_time(tp,T):
    def f(r):
        hit=getattr(r,f"tp_hit_{tp}_dt")
        if np.isfinite(hit) and hit<=T: return tp/100.0
        return getattr(r,f"bid_{T}")
    return f
for tp in [60,65,70]:
    for T in [60,90]:
        rpt(f"TP{tp}-or-time{T}",D,tp_or_time(tp,T))
# trailing stop from discrete grid: track running max of bid over dts; sell when bid drops >=drop below max
def trail(drop):
    def f(r):
        mx=-1;
        for dt in DTS:
            b=getattr(r,f"bid_{dt}")
            if not np.isfinite(b): continue
            if b>mx: mx=b
            elif mx-b>=drop: return b   # sell on pullback
        # never triggered -> last available bid (or hold)
        for dt in reversed(DTS):
            b=getattr(r,f"bid_{dt}")
            if np.isfinite(b): return b
        return np.nan
    return f
for dr in [0.03,0.05,0.08]:
    rpt(f"trailing-stop {dr}",D,trail(dr))
print("\n-- worst-case fee 0.07 --")
rpt("TIME+45 (fee0.07)",D,lambda r:r.bid_45,fee=0.07)
rpt("TP70-or-time60 (fee0.07)",D,tp_or_time(70,60),fee=0.07)
rpt("trailing 0.05 (fee0.07)",D,trail(0.05),fee=0.07)
