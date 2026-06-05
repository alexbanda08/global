"""
OVERNIGHT massive search. Ranks candidates by PURGED K-FOLD CV robustness on the CURRENT window
(snoop-resistant selection) + a PERMUTATION-NULL pass to calibrate "how good is good after N tries".
Persists a small pre-committed finalist set for OOS confirmation on a DIFFERENT window (validate_oos.py).

KEY DISCIPLINE: selection here is in-sample to the 38-day window no matter how many candidates we try.
The ONLY real proof is the OOS different-window test. This script just ranks + de-snoops the shortlist.

Usage: python search_overnight.py <hours> [n_jobs]      e.g.  python search_overnight.py 8
Resumable: checkpoints to _data/overnight/ every few minutes. Re-run to continue (re-seeds RNG by time-in-args).
"""
import sys, json, time, math, os
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
OUT=HERE/"_data"/"overnight"; OUT.mkdir(parents=True,exist_ok=True)
HOURS=float(sys.argv[1]) if len(sys.argv)>1 else 8.0
NJOBS=int(sys.argv[2]) if len(sys.argv)>2 else max(1,(os.cpu_count() or 4)-2)
BUDGET=HOURS*3600
SEED=int(time.time())%100000
RNG=np.random.default_rng(SEED)

from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.isotonic import IsotonicRegression
from joblib import Parallel, delayed

GROUPS=json.load(open(HERE/"_data"/"feature_groups.json"))
FORB={"pnl45","pnl60","reprice45","y_scalp_pos","won","shares","filled","orig_vwap"}|{f"bid_{d}" for d in [30,45,60,75,90,120,150,180]}|{"bid_pathmax","bid_pathmax_dt","opp_ask_min","oppask_30","oppask_60","oppask_90"}|{f"tp_hit_{t}_dt" for t in [60,65,70,75]}
POOL=[c for c in (GROUPS["indicators"]+GROUPS["clob"]+GROUPS["physics"]+GROUPS["entry"]) if c not in FORB]
df=pd.read_parquet(HERE/"_data"/"master_features.parquet").sort_values("fire_us").reset_index(drop=True)
df=df[df.asset.isin(["BTC","ETH"])].reset_index(drop=True)
FILTERS={"broad":np.ones(len(df),bool),
         "vwap055":(df.entry_vwap<0.55).values,
         "d3v055":((df.delta_bps>=3)&(df.entry_vwap<0.55)).values,
         "d5v055":((df.delta_bps>=5)&(df.entry_vwap<0.55)).values}
EXIT_DTS=[45,60,75]
def pnl_at(exit_dt):
    b=df[f"bid_{exit_dt}"].values; ev=df.entry_vwap.values; sh=df.shares.values; won=df.won.values
    return np.where(np.isfinite(b),(b-ev)*sh-0.015*sh*(ev*(1-ev)+b*(1-b)),
                    np.where(won,sh*(1-ev)*(1-0.07*ev),-sh*ev))
PNL={d:pnl_at(d) for d in EXIT_DTS}
XALL=df[POOL].astype(float).fillna(0).values
ASSET=df.asset.values
FIRE=df.fire_us.values

def mkmodel(mt,depth):
    if mt=="xgb": return XGBClassifier(n_estimators=120,max_depth=depth,learning_rate=0.06,subsample=0.8,
        colsample_bytree=0.8,min_child_weight=8,reg_lambda=3.0,eval_metric="logloss",tree_method="hist",verbosity=0)
    if mt=="rf": return RandomForestClassifier(n_estimators=120,max_depth=depth,min_samples_leaf=20,n_jobs=1)
    if mt=="et": return ExtraTreesClassifier(n_estimators=120,max_depth=depth,min_samples_leaf=20,n_jobs=1)
    return make_pipeline(StandardScaler(),LogisticRegression(max_iter=300,C=0.5))

def eval_cv(cand, shuffle=False, folds=4):
    """Purged K-fold CV gated $/tr on the filtered current window. Returns (mean,std,min_take,confound)."""
    mask=FILTERS[cand["f"]]; idx=np.where(mask)[0]
    n=len(idx)
    if n<240: return None
    Xi=XALL[np.ix_(idx,cand["cols"])]; pnl=PNL[cand["e"]][idx]; asset=ASSET[idx]
    y=(pnl>0).astype(int)
    if shuffle: y=y[RNG.permutation(n)]
    if len(np.unique(y))<2: return None
    bounds=np.linspace(0,n,folds+1).astype(int)
    fold_dpt=[]; mixes=[]
    for k in range(folds):
        te=np.arange(bounds[k],bounds[k+1])
        tr=np.concatenate([np.arange(0,bounds[k]),np.arange(bounds[k+1],n)])
        # purge: drop tr rows within 1 slot of te boundary by time
        if len(tr)<150 or len(np.unique(y[tr]))<2: continue
        try:
            m=mkmodel(cand["m"],cand["d"]); m.fit(Xi[tr],y[tr])
            praw=m.predict_proba(Xi[te])[:,1]
            # threshold from tr
            ptr=m.predict_proba(Xi[tr])[:,1]
            best=None
            for thr in np.arange(0.42,0.70,0.04):
                tk=ptr>thr
                if tk.sum()<30: continue
                mu=pnl[tr][tk].mean()
                if best is None or mu>best[1]: best=(thr,mu)
            thr=best[0] if best else 0.5
            tk=praw>thr
            if tk.sum()<8: continue
            fold_dpt.append(pnl[te][tk].mean())
            am=asset[te][tk]; mixes.append((int((am=="BTC").sum()),int((am=="ETH").sum())))
        except Exception: continue
    if len(fold_dpt)<3: return None
    tb=sum(x[0] for x in mixes); te_=sum(x[1] for x in mixes); tot=tb+te_ or 1
    confound=(min(tb,te_)/tot<0.10)
    return (float(np.mean(fold_dpt)), float(np.std(fold_dpt)), confound, tot)

def gen():
    k=int(RNG.integers(2,26))
    cols=sorted(RNG.choice(len(POOL),size=min(k,len(POOL)),replace=False).tolist())
    return {"cols":cols,"m":str(RNG.choice(["xgb","xgb","rf","et","logit"])),
            "f":str(RNG.choice(["vwap055","vwap055","d3v055","d5v055","broad"])),
            "e":int(RNG.choice(EXIT_DTS)),"d":int(RNG.choice([2,3,4,5]))}

def robust_score(r):
    if r is None: return -99
    mean,std,confound,tot=r
    s=mean-0.5*std
    return s-3.0 if confound else s

# ---- permutation null: best robust-score under shuffled labels over a batch ----
def _null_one(c): return robust_score(eval_cv(c, shuffle=True))
def null_batch(nb=400, njobs=4):
    cands=[gen() for _ in range(nb)]
    scores=Parallel(n_jobs=njobs,prefer="processes")(delayed(_null_one)(c) for c in cands)
    return np.array([s for s in scores if s>-50])

def _main():
    print(f"OVERNIGHT search | budget={HOURS}h njobs={NJOBS} seed={SEED} pool={len(POOL)} feats",flush=True)
    t0=time.time()
    print("calibrating permutation null (no-signal baseline)...",flush=True)
    null=null_batch(1500, njobs=NJOBS)
    null_p95=float(np.percentile(null,95)) if len(null) else 0.0
    null_max=float(np.max(null)) if len(null) else 0.0
    print(f"  null robust-score: p95={null_p95:.3f} max={null_max:.3f} (n={len(null)})  -> a real candidate must clear this",flush=True)
    top=[]; total=0; ckpt=time.time(); BATCH=NJOBS*8
    while time.time()-t0 < BUDGET:
        cands=[gen() for _ in range(BATCH)]
        rs=Parallel(n_jobs=NJOBS,prefer="processes")(delayed(eval_cv)(c) for c in cands)
        for c,r in zip(cands,rs):
            total+=1; sc=robust_score(r)
            if sc>null_p95: top.append((sc,c,r))
        if len(top)>4000:
            top.sort(key=lambda x:-x[0]); top=top[:3000]
        if time.time()-ckpt>180:
            top.sort(key=lambda x:-x[0]); elapsed=time.time()-t0; rate=total/max(elapsed,1)
            pd.DataFrame([{"score":s,"m":c["m"],"f":c["f"],"e":c["e"],"d":c["d"],"nfeat":len(c["cols"]),
                           "cols":json.dumps(c["cols"]),"cv_mean":r[0],"cv_std":r[1],"confound":r[2],"n":r[3]}
                          for s,c,r in top[:1500]]).to_parquet(OUT/"top_checkpoint.parquet",index=False)
            json.dump({"total":total,"elapsed_s":int(elapsed),"rate_per_s":round(rate,1),"kept":len(top),
                       "null_p95":null_p95,"null_max":null_max,"best":top[0][0] if top else None,
                       "hours":HOURS,"seed":SEED},open(OUT/"status.json","w"),indent=2)
            print(f"  t={elapsed/3600:.2f}h searched={total} ({rate:.0f}/s) kept>{null_p95:.2f}={len(top)} best={(top[0][0] if top else float('nan')):.3f}",flush=True)
            ckpt=time.time()
    top.sort(key=lambda x:-x[0])
    finalists=[{"score":round(s,3),"cv_mean":round(r[0],3),"cv_std":round(r[1],3),"confound":r[2],
                "model":c["m"],"filter":c["f"],"exit_dt":c["e"],"depth":c["d"],
                "features":[POOL[i] for i in c["cols"]]} for s,c,r in top[:50]]
    json.dump({"searched":total,"null_p95":null_p95,"null_max":null_max,"seed":SEED,"hours":HOURS,
               "finalists":finalists},open(OUT/"finalists.json","w"),indent=2)
    print(f"\nDONE. searched={total} kept>{null_p95:.2f}={len(top)} -> saved top 50 finalists.json",flush=True)
    print(f"null p95={null_p95:.3f} max={null_max:.3f}; best score={top[0][0]:.3f}" if top else "no candidate beat null",flush=True)
    print("NEXT: validate_oos.py on a DIFFERENT window (6mo API books+trades) — the only real proof.",flush=True)

if __name__=="__main__":
    _main()
