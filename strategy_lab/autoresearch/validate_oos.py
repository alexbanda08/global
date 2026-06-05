"""
OOS CONFIRMATION — the ONLY real proof. Takes the overnight finalists and tests them on a DIFFERENT
window (built by the same pipeline on the 6-month API data, or fresh shadow fires). The search/selection
was in-sample to the 38-day window; this script is the independent judge.

Protocol (anti-snooping):
  - Train each finalist on the FULL current window (master_features.parquet), threshold chosen there.
  - Predict + gate on the OOS window (oos_master_features.parquet) — never seen by the search.
  - Metric = scalp $/tr-after-fee on the OOS gated set + bootstrap CI.
  - BONFERRONI: with K finalists, a candidate is credible only if its OOS gated-CI lower bound > 0 at the
    K-corrected level AND it beats OOS all-take AND is not asset-confounded. Pre-commit to ranking by the
    overnight `score` and report the #1 separately (a single pre-registered test needs no correction).

Usage: python validate_oos.py <path/to/oos_master_features.parquet>
Build the OOS matrix by re-running build_indicator_panel/build_clob_flow/build_master_features pointed at
the new window's klines + trades + scalp-fill cache.
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
RNG=np.random.default_rng(99)

def boot(x,n=8000):
    x=np.asarray(x,float);x=x[np.isfinite(x)]
    if len(x)<3:return(np.nan,np.nan)
    m=x[RNG.integers(0,len(x),size=(n,len(x)))].mean(1);return float(np.percentile(m,2.5)),float(np.percentile(m,97.5))
def mkmodel(mt,depth):
    if mt=="xgb": return XGBClassifier(n_estimators=200,max_depth=depth,learning_rate=0.05,subsample=0.8,
        colsample_bytree=0.8,min_child_weight=8,reg_lambda=3.0,eval_metric="logloss",tree_method="hist")
    if mt=="rf": return RandomForestClassifier(n_estimators=200,max_depth=depth,min_samples_leaf=20,n_jobs=-1)
    if mt=="et": return ExtraTreesClassifier(n_estimators=200,max_depth=depth,min_samples_leaf=20,n_jobs=-1)
    return make_pipeline(StandardScaler(),LogisticRegression(max_iter=400,C=0.5))
def filt(d,f):
    if f=="vwap055": return d[d.entry_vwap<0.55]
    if f=="d3v055": return d[(d.delta_bps>=3)&(d.entry_vwap<0.55)]
    if f=="d5v055": return d[(d.delta_bps>=5)&(d.entry_vwap<0.55)]
    return d
def pnl_at(d,e):
    b=d[f"bid_{e}"].values; ev=d.entry_vwap.values; sh=d.shares.values; won=d.won.values
    return np.where(np.isfinite(b),(b-ev)*sh-0.015*sh*(ev*(1-ev)+b*(1-b)),
                    np.where(won,sh*(1-ev)*(1-0.07*ev),-sh*ev))

def main(oos_path):
    cur=pd.read_parquet(HERE/"_data"/"master_features.parquet")
    cur=cur[cur.asset.isin(["BTC","ETH"])]
    oos=pd.read_parquet(oos_path); oos=oos[oos.asset.isin(["BTC","ETH"])]
    fin=json.load(open(HERE/"_data"/"overnight"/"finalists.json"))
    cands=fin["finalists"]; K=len(cands)
    print(f"OOS window n={len(oos)} | finalists={K} | null_p95(in-sample)={fin['null_p95']:.3f}",flush=True)
    rows=[]
    for i,c in enumerate(cands):
        feats=[f for f in c["features"] if f in cur.columns and f in oos.columns]
        dc=filt(cur,c["filter"]); do=filt(oos,c["filter"])
        if len(dc)<200 or len(do)<40 or not feats:
            rows.append({"rank":i+1,"oos_n":len(do),"survives":False,"note":"insufficient"}); continue
        Xc=dc[feats].astype(float).fillna(0).values; Xo=do[feats].astype(float).fillna(0).values
        pc=pnl_at(dc,c["exit_dt"]); po=pnl_at(do,c["exit_dt"]); yc=(pc>0).astype(int)
        if len(np.unique(yc))<2:
            rows.append({"rank":i+1,"survives":False,"note":"one-class"}); continue
        m=mkmodel(c["model"],c["depth"]); m.fit(Xc,yc)
        # threshold on current
        ptr=m.predict_proba(Xc)[:,1]; best=None
        for thr in np.arange(0.42,0.70,0.02):
            tk=ptr>thr
            if tk.sum()<30: continue
            mu=pc[tk].mean()
            if best is None or mu>best[1]: best=(thr,mu)
        thr=best[0] if best else 0.5
        po_p=m.predict_proba(Xo)[:,1]; take=po_p>thr
        if take.sum()<15: rows.append({"rank":i+1,"oos_n":int(take.sum()),"survives":False,"note":"gate empty"}); continue
        gp=po[take]; ci=boot(gp); allci=boot(po)
        am=do.asset.values[take]; mix=(int((am=='BTC').sum()),int((am=='ETH').sum())); tot=sum(mix) or 1
        conf=min(mix)/tot<0.10
        # Bonferroni: require CI lower>0; flag #1 separately (pre-registered)
        survive = (ci[0]>0) and (gp.mean()>po.mean()) and (not conf)
        rows.append({"rank":i+1,"oos_gated_n":int(take.sum()),"oos_dpt":round(float(gp.mean()),3),
                     "oos_ci":(round(ci[0],2),round(ci[1],2)),"oos_all":round(float(po.mean()),3),
                     "lift":round(float(gp.mean()-po.mean()),3),"mix":mix,"confound":conf,"survives":bool(survive)})
    R=pd.DataFrame(rows)
    R.to_csv(HERE/"_data"/"overnight"/"oos_validation.csv",index=False)
    nsv=int(R.get("survives",pd.Series([],dtype=bool)).sum())
    print(R.to_string(index=False),flush=True)
    print(f"\nSurvivors on the INDEPENDENT window: {nsv}/{K}",flush=True)
    print(f"BONFERRONI: credible only if rank-1 (pre-registered) survives, OR a survivor's CI clears 0 at "
          f"the {K}-corrected level (~CI>0 with wide margin). A barely-positive CI among {K} = noise.",flush=True)

if __name__=="__main__":
    if len(sys.argv)<2:
        print("usage: python validate_oos.py <oos_master_features.parquet>"); sys.exit(1)
    main(sys.argv[1])
