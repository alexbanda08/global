"""
04 — Walk-forward robustness of the logged-feature gates.
Split each sleeve's fires chronologically into half1 (train) / half2 (test).
Evaluate FIXED, low-DOF gates on BOTH halves vs that half's baseline.
A gate GENERALIZES only if it improves mean pnl in BOTH halves (sign-stable).
This filters out in-sample-selected session/threshold artifacts.
"""
import pandas as pd, numpy as np, os
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
OUTD=os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30")
fr=pd.read_parquet(os.path.join(OUTD,"_results","fires_resolved_all.parquet")).sort_values("at")

GATES = {
 "evcap_0.80": lambda g: g.entry_vwap<=0.80,
 "evcap_0.75": lambda g: g.entry_vwap<=0.75,
 "evcap_0.70": lambda g: g.entry_vwap<=0.70,
 "vsum_1.25":  lambda g: g.vwap_sum<=1.25,
 "vsum_1.30":  lambda g: g.vwap_sum<=1.30,
 "xspread_0.25":lambda g: g.cross_spread<=0.25,
 "depth_1000": lambda g: g.own_depth>=1000,
 "drop_US":    lambda g: ~g.hour.mod(24).between(14,21),
 "keep_EU":    lambda g: g.hour.mod(24).between(6,13),
 "keep_ASIA_EU":lambda g: ~g.hour.mod(24).between(14,21),
 "dir_UP":     lambda g: g.direction=="UP",
 "dir_DOWN":   lambda g: g.direction=="DOWN",
}

def mean_total(g):
    return (round(g.pnl_usd.mean(),3) if len(g) else np.nan, round(g.pnl_usd.sum(),1), len(g),
            round(100*g.won.mean(),1) if len(g) else np.nan)

rows=[]
for s in sorted(fr.sleeve.unique()):
    g=fr[fr.sleeve==s]
    if len(g)<40: continue
    mid=len(g)//2
    h1=g.iloc[:mid]; h2=g.iloc[mid:]
    b1=mean_total(h1); b2=mean_total(h2)
    for gn,gf in GATES.items():
        try:
            s1=mean_total(h1[gf(h1)]); s2=mean_total(h2[gf(h2)])
        except Exception:
            continue
        if s1[2]<10 or s2[2]<10: continue   # need >=10 kept in each half
        d1=s1[0]-b1[0]; d2=s2[0]-b2[0]
        gen = (d1>0 and d2>0)
        rows.append(dict(sleeve=s, gate=gn,
            h1_n=s1[2], h1_d=round(d1,3), h2_n=s2[2], h2_d=round(d2,3),
            generalizes=gen,
            full_mean=round(g.pnl_usd.mean(),3), full_total=round(g.pnl_usd.sum(),1)))

res=pd.DataFrame(rows)
res.to_csv(os.path.join(OUTD,"_results","walkforward_gates.csv"),index=False)

print("=== GATES THAT GENERALIZE (improve mean in BOTH chronological halves) ===")
gen=res[res.generalizes].sort_values(["sleeve","h2_d"],ascending=[True,False])
for s,sub in gen.groupby("sleeve"):
    base=fr[fr.sleeve==s]
    print(f"\n## {s}  (full n{len(base)} mean{base.pnl_usd.mean():.3f} tot{base.pnl_usd.sum():.1f})")
    for _,r in sub.iterrows():
        print(f"   {r['gate']:13s} h1:+{r['h1_d']:.3f}(n{r['h1_n']})  h2:+{r['h2_d']:.3f}(n{r['h2_n']})")
print("\n=== sleeves with NO generalizing gate ===")
alls=set(res.sleeve.unique()); gens=set(gen.sleeve.unique())
print(sorted(alls-gens))
print("\nWROTE _results/walkforward_gates.csv")
