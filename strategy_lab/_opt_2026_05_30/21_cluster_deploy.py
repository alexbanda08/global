"""
21 — Pass 2: per-market signal-overlap clustering + variance + decorrelated deploy set.
"same variance" = sleeves that make the SAME bets (high (slug,direction) Jaccard) -> redundant.
Deploy-together = pick one leader per cluster (decorrelated) per market.
"""
import pandas as pd, numpy as np, os
OUTD=r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_opt_2026_05_30\_results"
q=pd.read_csv(os.path.join(OUTD,"qualifying_sleeves.csv"))
R=pd.read_parquet(os.path.join(OUTD,"all_sleeve_fires.parquet"))
# exclude deprecated families
BAD=("_SELL","HEDGE","INV_NIGHT","_volume","_INV","sniper_INV","_FADE","fade")
q=q[~q.sleeve.str.contains("|".join(BAD), case=False, regex=True)].copy()
# mint_sell is a maker strat, not directional up/down -> separate
mint=q[q.sleeve.str.contains("mint_sell")]; q=q[~q.sleeve.str.contains("mint_sell")]
R=R[R.sleeve.isin(set(q.sleeve))]
# per-sleeve variance / sharpe
v=R.groupby("sleeve").pnl.agg(std=lambda x:round(x.std(),3)).reset_index()
q=q.merge(v,on="sleeve",how="left"); q["sharpe"]=(q.dpt/q["std"]).round(3)
# (slug,direction) set per sleeve
keyset={s: set(zip(g.slug,g.direction)) for s,g in R.groupby("sleeve")}
def jacc(a,b):
    A,B=keyset.get(a,set()),keyset.get(b,set())
    if not A or not B: return 0.0
    return len(A&B)/len(A|B)
def cluster(sleeves, thr=0.5):
    # greedy: union sleeves with pairwise jaccard>thr
    cl=[]; used=set()
    sl=sorted(sleeves, key=lambda s:-q.set_index("sleeve").loc[s,"total"])
    for s in sl:
        if s in used: continue
        grp=[s]; used.add(s)
        for t in sl:
            if t in used: continue
            if max(jacc(t,m) for m in grp)>thr: grp.append(t); used.add(t)
        cl.append(grp)
    return cl
print("=== QUALIFYING (non-deprecated, directional) by market ===")
out_lines=[]
for (asset,tf),sub in q.sort_values("total",ascending=False).groupby(["asset","tf"]):
    if not asset or not tf: continue
    sleeves=sub.sleeve.tolist()
    cls=cluster(sleeves,0.5)
    print(f"\n##### {asset} {tf}  ({len(sleeves)} qualifying, {len(cls)} decorrelated clusters)")
    print(sub[["sleeve","n","wr","dpt","total","std","sharpe"]].to_string(index=False))
    leaders=[]
    for i,grp in enumerate(cls):
        best=max(grp, key=lambda s:q.set_index("sleeve").loc[s,"total"])
        leaders.append(best)
        if len(grp)>1:
            ov=[round(jacc(best,o),2) for o in grp if o!=best]
            print(f"  cluster{i+1} (REDUNDANT, overlap~): leader={best.split('poly_')[-1][:40]}  +{len(grp)-1} dup (jacc {ov})")
        else:
            print(f"  cluster{i+1} (unique): {best.split('poly_')[-1][:46]}")
    # combined decorrelated portfolio stats (leaders)
    lead=sub[sub.sleeve.isin(leaders)]
    comb_total=lead.total.sum(); comb_var=(lead["std"]**2).sum()  # independent-sum variance
    print(f"  >>> DEPLOY-TOGETHER ({len(leaders)} decorrelated): total=${comb_total:.0f}  indep-portfolio-std~${comb_var**0.5:.2f}")
    print(f"      leaders: {[l.split('poly_')[-1][:36] for l in leaders]}")
print("\n=== MAKER (separate, not directional up/down) ===")
print(mint[["sleeve","n","wr","dpt","total"]].to_string(index=False) if len(mint) else "  none")
q.to_csv(os.path.join(OUTD,"qualifying_with_variance.csv"),index=False)
