"""Disambiguate: does the physics vol-gate add edge WITHIN each asset (BTC, ETH separately,
asset-scaled thresholds), or is it just selecting BTC? Scalp TIME+60, fee=0.015, deployed cell."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
c = pd.read_parquet(ROOT/"strategy_lab"/"directional"/"_results"/"scalp_hedge_physics_cache_2026_06_03.parquet")
RNG = np.random.default_rng(9)
def boot(x,n=8000):
    x=np.asarray(x,float); x=x[np.isfinite(x)]
    if len(x)<3: return (np.nan,np.nan)
    m=x[RNG.integers(0,len(x),size=(n,len(x)))].mean(1); return float(np.percentile(m,2.5)),float(np.percentile(m,97.5))
def t(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]
    return np.nan if len(x)<3 or x.std(ddof=1)==0 else x.mean()/(x.std(ddof=1)/np.sqrt(len(x)))
def hold07(ev,sh,won): return sh*(1-ev)*(1-0.07*ev) if won else -sh*ev
def sc(ev,sh,b,won,fee=0.015):
    if not np.isfinite(b): return hold07(ev,sh,won)
    return (b-ev)*sh - fee*sh*(ev*(1-ev)+b*(1-b))
def s60(d): return np.array([sc(r.entry_vwap,r.shares,r.bid_60,r.won) for r in d.itertuples()])
def rpt(name,d):
    p=s60(d); p=p[np.isfinite(p)]
    if len(p)<3: print(f"  {name:34} n={len(p):3} (too few)"); return
    ci=boot(p); print(f"  {name:34} n={len(p):3} $/tr={p.mean():+6.2f} t={t(p):4.1f} CI[{ci[0]:+.2f},{ci[1]:+.2f}]")
F=c[c.filled & np.isfinite(c.get('phys_dist_abs'))]
D=F[(F.asset.isin(['BTC','ETH']))&(F.delta_bps>=5)&(F.entry_vwap<0.55)]
# asset-scaled thresholds: BTC dist in $ (~95k), ETH dist in $ (~2.6k). scale ~ price ratio.
for asset,dthr,sthr in [('BTC',[20,30,40,60],[10,15,20]),('ETH',[0.5,0.8,1.2,2.0],[0.3,0.5,0.8])]:
    da=D[D.asset==asset]
    print(f"\n=== {asset} (deployed cell n={len(da)}) ===")
    rpt(f"{asset} baseline (all)", da)
    for dt in dthr: rpt(f"{asset} dist_abs>={dt}", da[da.phys_dist_abs>=dt])
    for st in sthr: rpt(f"{asset} speed_abs>={st}", da[da.phys_speed_abs>=st])
    rpt(f"{asset} d_speed>=0", da[da.phys_d_speed>=0])
    rpt(f"{asset} margin>0", da[da.phys_margin>0])
    # within-asset vol TERTILES (asset-neutral, removes scale confound)
    if len(da)>=15:
        q=da.phys_speed_abs.quantile([1/3,2/3]).values
        rpt(f"{asset} speed LOW tertile", da[da.phys_speed_abs<=q[0]])
        rpt(f"{asset} speed MID tertile", da[(da.phys_speed_abs>q[0])&(da.phys_speed_abs<=q[1])])
        rpt(f"{asset} speed HIGH tertile", da[da.phys_speed_abs>q[1]])
