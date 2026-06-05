"""
physics_experiments.py — cheap experiments on physics_fires_enriched.parquet.
The EDGE metric is NET PnL/fire after real fees (pnl_curve), NOT win rate.
Run one: C:/Python314/python.exe strategy_lab/physics/physics_experiments.py --exp E1
Experiments: E1 gap/EV core | E2 multi-gate ranked by PnL | E3 d_speed |
             E4 gap-harvest 2D (entry_vwap x dist) | E5 spread + tf split
"""
from __future__ import annotations
import sys, argparse, itertools
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT = ROOT / "strategy_lab" / "physics" / "_results"
pd.set_option("display.width", 220, "display.max_columns", 30)


def load():
    df = pd.read_parquet(OUT / "physics_fires_enriched.parquet")
    return df[df.valid].copy()


def row(name, d):
    if len(d) == 0:
        return dict(cfg=name, n=0)
    return dict(cfg=name, n=len(d), WR=round(100*d.won.mean(),1),
                implied=round(d.implied.mean(),3),
                gap_pp=round(100*(d.won.mean()-d.implied.mean()),1),
                net_curve=round(d.pnl_curve.mean(),4), tot_curve=round(d.pnl_curve.sum(),1),
                net_legacy=round(d.pnl_legacy.mean(),4))


def split(df):
    df = df.sort_values("slot_start_us"); c = int(len(df)*0.6)
    return df.iloc[:c], df.iloc[c:]


def E1(df):
    print("=== E1  EV CORE (net PnL/fire after real fees is the verdict) ===")
    res = [row("continuation_all", df),
           row("WEAK_COMBO 30/10", df[~((df.dist_abs<30)&(df.speed_away<10))]),
           row("WEAK_COMBO 40/15", df[~((df.dist_abs<40)&(df.speed_away<15))]),
           row("blocked 30/10", df[((df.dist_abs<30)&(df.speed_away<10))])]
    print(pd.DataFrame(res).to_string(index=False))
    print("\n  entry_vwap ceiling sweep on WEAK_COMBO-30/10 kept (the 'gap' favors cheap entries):")
    kept = df[~((df.dist_abs<30)&(df.speed_away<10))]
    rr = [row(f"vwap<={c}", kept[kept.entry_vwap<=c]) for c in [0.80,0.85,0.90,0.93,0.95,0.99]]
    print(pd.DataFrame(rr).to_string(index=False))


def E2(df):
    print("=== E2  multi-gate WEAK_COMBO, ranked by TEST net PnL (train60/test40) ===")
    tr, te = split(df)
    P = {"dist_abs":[10,20,30,40,50],"speed_away":[0,5,10,15],"cross":[1,2,3,5],"margin":[-0.5,0,1,2]}
    out=[]
    for a,b in itertools.combinations(P,2):
        for ta in P[a]:
            for tb in P[b]:
                kt = ~((tr[a]<ta)&(tr[b]<tb)); ke = ~((te[a]<ta)&(te[b]<tb))
                if ke.mean()<0.3 or kt.mean()<0.3 or ke.sum()<50: continue
                out.append(dict(pa=a,ta=ta,pb=b,tb=tb,
                    tr_net=round(tr.pnl_curve[kt].mean(),4), te_net=round(te.pnl_curve[ke].mean(),4),
                    te_WR=round(100*te.won[ke].mean(),1), keep=round(ke.mean(),2), n=int(ke.sum())))
    g=pd.DataFrame(out)
    g=g[(g.tr_net>0)&(g.te_net>0)].sort_values("te_net",ascending=False)
    print(f"  {len(g)} configs +net both halves. Top 12:")
    print(g.head(12).to_string(index=False))
    print(f"\n  single-gate dist_abs>=X (no speed): "
          + " ".join(f"X{x}:{df[df.dist_abs>=x].pnl_curve.mean():+.3f}(n{len(df[df.dist_abs>=x])})" for x in [20,30,40,50]))


def E3(df):
    print("=== E3  d_speed (Δspeed last 30s; <0 = inertia fading) ===")
    d=df.dropna(subset=["d_speed"])
    res=[row("all",d), row("d_speed>=0 (accel)", d[d.d_speed>=0]), row("d_speed<0 (fading)", d[d.d_speed<0])]
    k=d[~((d.dist_abs<30)&(d.speed_away<10))]
    res+=[row("WC30/10",k), row("WC30/10 + d_speed>=0", k[k.d_speed>=0])]
    print(pd.DataFrame(res).to_string(index=False))


def E4(df):
    print("=== E4  GAP-HARVEST 2D: net PnL by (entry_vwap ceiling x dist_min) ===")
    vmax=[0.80,0.85,0.90,0.95,0.99]; dmin=[0,15,30,50]
    M=[]
    for v in vmax:
        r={"vwap<=":v}
        for dm in dmin:
            s=df[(df.entry_vwap<=v)&(df.dist_abs>=dm)]
            r[f"d>={dm}"]=f"{s.pnl_curve.mean():+.3f}/n{len(s)}" if len(s) else "-"
        M.append(r)
    print(pd.DataFrame(M).to_string(index=False))


def E5(df):
    print("=== E5  spread filter + tf split (net PnL curve) ===")
    res=[row("all",df)]
    for sp in [0.02,0.05,0.10]:
        res.append(row(f"spread<={sp}", df[df.spread<=sp]))
    for tf in ["5m","15m"]:
        res.append(row(f"tf={tf}", df[df.tf==tf]))
        kk=df[(df.tf==tf)&~((df.dist_abs<30)&(df.speed_away<10))]
        res.append(row(f"tf={tf} WC30/10", kk))
    print(pd.DataFrame(res).to_string(index=False))


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--exp",default="all"); a=ap.parse_args()
    df=load(); print(f"loaded {len(df)} valid fires\n")
    fns={"E1":E1,"E2":E2,"E3":E3,"E4":E4,"E5":E5}
    for k in ([a.exp] if a.exp!="all" else list(fns)):
        fns[k](df); print()
