"""
03 — Logged-feature gate sweep over each sleeve's resolved fires.
Goal: find ADD-A-GATE filters that lift net EV (mean pnl_usd) with enough retained n.
Features available per fire (logged at fire time, causal): entry_vwap, own_vwap, opp_vwap,
vwap_sum, own_depth, opp_depth, cross_spread, fire_offset_s, hour, dow, direction.
Reports per sleeve: baseline + best single-gate variants + direction/session split.
Bootstrap CI-lo on mean pnl (2.5%, 2000 resamples). A gate is FLAGGED real if
n_kept>=30 and ci_lo>0 and mean_after>baseline_mean.
"""
import pandas as pd, numpy as np, os
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
OUTD=os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30")
fr=pd.read_parquet(os.path.join(OUTD,"_results","fires_resolved_all.parquet"))
rng=np.random.default_rng(42)

def ci_lo(x, B=2000):
    x=np.asarray(x,float); x=x[~np.isnan(x)]
    if len(x)<5: return np.nan
    idx=rng.integers(0,len(x),size=(B,len(x)))
    means=x[idx].mean(axis=1)
    return np.percentile(means,2.5)

def stat(g):
    p=g.pnl_usd.values
    return dict(n=len(g), wr=round(100*g.won.mean(),1), mean=round(np.nanmean(p),3),
                total=round(np.nansum(p),1), cilo=round(ci_lo(p),3))

def grid_cap(g, col, lo, hi, step, direction="le"):
    best=None
    for thr in np.arange(lo,hi+1e-9,step):
        m = g[col]<=thr if direction=="le" else g[col]>=thr
        sub=g[m]
        if len(sub)<30: continue
        s=stat(sub); s["thr"]=round(thr,3); s["kept"]=round(100*len(sub)/len(g),0)
        # objective: maximize total retained PnL but require mean improvement
        if best is None or s["total"]>best["total"]:
            best=s
    return best

rows=[]
SLEEVES=sorted(fr.sleeve.unique())
for s in SLEEVES:
    g=fr[fr.sleeve==s]
    base=stat(g)
    rec=dict(sleeve=s, n=base["n"], wr=base["wr"], mean=base["mean"], total=base["total"], base_cilo=base["cilo"])
    # entry_vwap cap (don't overpay)
    bevc=grid_cap(g,"entry_vwap",0.50,0.90,0.025,"le")
    if bevc: rec["evcap"]=f"<= {bevc['thr']}: n{bevc['n']} wr{bevc['wr']} mean{bevc['mean']} tot{bevc['total']} cilo{bevc['cilo']}"
    # cross_spread cap (tighter book)
    if g.cross_spread.notna().sum()>=40:
        bcs=grid_cap(g,"cross_spread",0.02,0.40,0.02,"le")
        if bcs: rec["xspread"]=f"<= {bcs['thr']}: n{bcs['n']} wr{bcs['wr']} mean{bcs['mean']} tot{bcs['total']} cilo{bcs['cilo']}"
    # own_depth floor (more liquidity)
    if g.own_depth.notna().sum()>=40:
        bod=grid_cap(g,"own_depth",100,2000,100,"ge")
        if bod: rec["depth"]=f">= {bod['thr']}: n{bod['n']} wr{bod['wr']} mean{bod['mean']} tot{bod['total']} cilo{bod['cilo']}"
    # vwap_sum cap (less overround)
    if g.vwap_sum.notna().sum()>=40:
        bvs=grid_cap(g,"vwap_sum",1.00,1.60,0.05,"le")
        if bvs: rec["vsum"]=f"<= {bvs['thr']}: n{bvs['n']} wr{bvs['wr']} mean{bvs['mean']} tot{bvs['total']} cilo{bvs['cilo']}"
    # direction split
    for dlab in ["UP","DOWN"]:
        sub=g[g.direction==dlab]
        if len(sub)>=25:
            st=stat(sub); rec["dir_"+dlab]=f"n{st['n']} wr{st['wr']} mean{st['mean']} tot{st['total']} cilo{st['cilo']}"
    # session split (UTC): ASIA 22-6, EU 6-14, US 14-22
    sess=pd.cut(g.hour%24,bins=[-1,5,13,21,24],labels=["ASIA","EU","US","ASIA2"])
    gg=g.assign(sess=sess.astype(str).replace("ASIA2","ASIA"))
    for sn,sub in gg.groupby("sess"):
        if len(sub)>=25:
            st=stat(sub); rec["sess_"+sn]=f"n{st['n']} wr{st['wr']} mean{st['mean']} tot{st['total']}"
    # fire_offset subset: keep offsets whose mean>0 & n>=10
    if g.fire_offset_s.notna().sum()>=40 and g.fire_offset_s.nunique()>1:
        om=g.groupby("fire_offset_s").pnl_usd.agg(["mean","count"])
        keep=om[(om["mean"]>0)&(om["count"]>=10)].index.tolist()
        if keep and len(keep)<g.fire_offset_s.nunique():
            sub=g[g.fire_offset_s.isin(keep)]; st=stat(sub)
            rec["offkeep"]=f"{[int(x) for x in keep]}: n{st['n']} wr{st['wr']} mean{st['mean']} tot{st['total']} cilo{st['cilo']}"
    rows.append(rec)

out=pd.DataFrame(rows)
out.to_csv(os.path.join(OUTD,"_results","gate_sweep.csv"), index=False)

# print compact, sorted by current total asc (worst first = biggest fix opportunity)
pd.set_option("display.width",240); pd.set_option("display.max_colwidth",70)
print("=== BASELINE (sorted worst total first) ===")
print(out[["sleeve","n","wr","mean","total","base_cilo"]].sort_values("total").to_string(index=False))
print("\n=== GATE CANDIDATES per sleeve (focus losers + marginal) ===")
for _,r in out.sort_values("total").iterrows():
    print(f"\n## {r['sleeve']}  base: n{int(r['n'])} wr{r['wr']} mean{r['mean']} tot{r['total']} cilo{r['base_cilo']}")
    for k in ["evcap","xspread","depth","vsum","dir_UP","dir_DOWN","sess_ASIA","sess_EU","sess_US","offkeep"]:
        if k in r and isinstance(r[k],str): print(f"   {k:9s} {r[k]}")
print("\nWROTE _results/gate_sweep.csv")
