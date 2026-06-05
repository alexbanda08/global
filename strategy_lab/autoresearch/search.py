"""
REAL autoresearch search — randomized over the candidate space, with proper anti-snooping discipline:
  3-way time split: TRAIN [0,0.6)  DEVTEST [0.6,0.75)  LOCKBOX [0.75,1.0)
  - gate threshold chosen on TRAIN; candidate RANKED on DEVTEST gated $/tr (lockbox never touched in search)
  - confound penalty (>90% one asset) + min gated-n
  - after searching N candidates, the TOP-K finalists are evaluated ONCE on LOCKBOX
  - Bonferroni: a finalist "survives" only if its lockbox gated-CI lower bound > 0 AND it beats all-take
    (report the count tested so significance can be deflated)
Writes AUTORESEARCH_SEARCH_RESULTS_2026_06_03.md + search_log.parquet.
"""
import sys, json, time, itertools
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.isotonic import IsotonicRegression
RNG=np.random.default_rng(2027)
N_SEARCH=int(sys.argv[1]) if len(sys.argv)>1 else 800
TOPK=20

GROUPS=json.load(open(HERE/"_data"/"feature_groups.json"))
FORB={"pnl45","pnl60","reprice45","y_scalp_pos","won","shares","filled","orig_vwap"}|{f"bid_{d}" for d in [30,45,60,75,90,120,150,180]}|{"bid_pathmax","bid_pathmax_dt","opp_ask_min","oppask_30","oppask_60","oppask_90"}|{f"tp_hit_{t}_dt" for t in [60,65,70,75]}
POOL=[c for c in (GROUPS["indicators"]+GROUPS["clob"]+GROUPS["physics"]+GROUPS["entry"]) if c not in FORB]
df=pd.read_parquet(HERE/"_data"/"master_features.parquet").sort_values("fire_us").reset_index(drop=True)
df=df[df.asset.isin(["BTC","ETH"])].reset_index(drop=True)

def pnl_at(d,exit_dt):
    b=d[f"bid_{exit_dt}"].values; ev=d.entry_vwap.values; sh=d.shares.values; won=d.won.values
    return np.where(np.isfinite(b),(b-ev)*sh-0.015*sh*(ev*(1-ev)+b*(1-b)),
                    np.where(won,sh*(1-ev)*(1-0.07*ev),-sh*ev))
def boot(x,n=6000):
    x=np.asarray(x,float);x=x[np.isfinite(x)]
    if len(x)<3:return(np.nan,np.nan)
    m=x[RNG.integers(0,len(x),size=(n,len(x)))].mean(1);return float(np.percentile(m,2.5)),float(np.percentile(m,97.5))

def mkmodel(mt,depth):
    if mt=="xgb": return XGBClassifier(n_estimators=180,max_depth=depth,learning_rate=0.05,subsample=0.8,
        colsample_bytree=0.8,min_child_weight=8,reg_lambda=3.0,eval_metric="logloss",tree_method="hist")
    if mt=="rf": return RandomForestClassifier(n_estimators=200,max_depth=depth,min_samples_leaf=20,n_jobs=-1)
    return make_pipeline(StandardScaler(),LogisticRegression(max_iter=400,C=0.5))

FILTERS={"broad":lambda d:d,"vwap055":lambda d:d[d.entry_vwap<0.55],
         "d3v055":lambda d:d[(d.delta_bps>=3)&(d.entry_vwap<0.55)],
         "d5v055":lambda d:d[(d.delta_bps>=5)&(d.entry_vwap<0.55)]}

def eval_candidate(cand, lockbox=False):
    d=FILTERS[cand["filter"]](df).reset_index(drop=True)
    n=len(d)
    if n<200: return None
    c1=int(n*0.60); c2=int(n*0.75)
    feats=[f for f in cand["features"] if f in d.columns]
    if not feats: return None
    X=d[feats].astype(float).fillna(0).values
    pnl=pnl_at(d,cand["exit_dt"]); y=(pnl>0).astype(int)
    tr=slice(0,c1); dv=slice(c1,c2); lk=slice(c2,n)
    if len(np.unique(y[tr]))<2: return None
    m=mkmodel(cand["model"],cand["depth"])
    try: m.fit(X[tr],y[tr])
    except Exception: return None
    praw=m.predict_proba(X)[:,1]
    iso=IsotonicRegression(out_of_bounds="clip"); iso.fit(praw[tr][-1200:],y[tr][-1200:]); p=iso.transform(praw)
    # threshold chosen on TRAIN
    best=None
    for thr in np.round(np.arange(0.40,0.72,0.02),3):
        tk=p[tr]>thr
        if tk.sum()<40:continue
        mu=pnl[tr][tk].mean()
        if best is None or mu>best[1]: best=(thr,mu)
    thr=best[0] if best else 0.5
    seg = lk if lockbox else dv
    take=p[seg]>thr; seg_pnl=pnl[seg]
    if take.sum()<15: return None
    gp=seg_pnl[take]
    asset_seg=d.asset.values[seg][take]
    mix={"BTC":int((asset_seg=="BTC").sum()),"ETH":int((asset_seg=="ETH").sum())}
    tot=sum(mix.values()) or 1
    confound=(min(mix.values())/tot<0.10)
    out={"score":float(gp.mean()),"all":float(seg_pnl.mean()),"n_take":int(take.sum()),
         "lift":float(gp.mean()-seg_pnl.mean()),"mix":mix,"confound":confound,"thr":thr,"nfeat":len(feats)}
    if lockbox: out["ci"]=tuple(round(v,3) for v in boot(gp)); out["all_ci"]=tuple(round(v,3) for v in boot(seg_pnl))
    return out

# ---- random candidate space ----
def gen():
    k=int(RNG.integers(2,18))
    feats=list(RNG.choice(POOL,size=min(k,len(POOL)),replace=False))
    return {"features":feats,"model":str(RNG.choice(["xgb","xgb","rf","logit"])),
            "filter":str(RNG.choice(["vwap055","vwap055","d3v055","d5v055","broad"])),
            "exit_dt":int(RNG.choice([45,60])),"depth":int(RNG.choice([3,4,5]))}

t0=time.time(); cands=[];
for i in range(N_SEARCH):
    c=gen(); r=eval_candidate(c,lockbox=False)
    if r is None: continue
    sc=r["score"]-(3.0 if r["confound"] else 0.0)
    cands.append((sc,c,r))
    if (i+1)%100==0: print(f"  searched {i+1}/{N_SEARCH}  kept={len(cands)}  best_dev={max(x[0] for x in cands):.2f}  ({time.time()-t0:.0f}s)",flush=True)
cands.sort(key=lambda x:-x[0])
print(f"\nsearched {N_SEARCH}, valid {len(cands)}. Top devtest candidates -> lockbox confirm (Bonferroni n={TOPK}):",flush=True)

finalists=[]
for sc,c,rdev in cands[:TOPK]:
    rl=eval_candidate(c,lockbox=True)
    if rl is None: continue
    survives = (not rl["confound"]) and rl["ci"][0]>0 and rl["lift"]>0 and rl["all_ci"][0]>-99
    finalists.append((c,rdev,rl,survives))

L=["# autoresearch SEARCH results — 2026-06-03",f"","Searched **{N_SEARCH}** random candidates "
   f"(feature-subset × model × filter × exit). Ranked on DEVTEST; top {TOPK} confirmed ONCE on the time-held-out "
   f"LOCKBOX. A finalist 'survives' only if lockbox gated-CI>0, beats all-take, not asset-confounded — and even "
   f"then must be deflated for the {TOPK} multiple comparisons (Bonferroni: treat CI>0 as suggestive, not proof).",
   "","| rank | filter | model | nfeat | exit | dev $/tr | LOCKBOX gated $/tr | lock CI | all-take | lift | mix | survives |",
   "|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|"]
for i,(c,rd,rl,sv) in enumerate(finalists):
    L.append(f"| {i+1} | {c['filter']} | {c['model']} | {rl['nfeat']} | {c['exit_dt']} | {rd['score']:.2f} "
             f"| {rl['score']:.2f} | [{rl['ci'][0]:+.2f},{rl['ci'][1]:+.2f}] | {rl['all']:.2f} | {rl['lift']:+.2f} "
             f"| B{rl['mix']['BTC']}/E{rl['mix']['ETH']} | {'✅' if sv else '—'} |")
nsv=sum(1 for *_,sv in finalists if sv)
L+= ["",f"## Verdict","",f"- Survivors (raw CI>0, confound-free, beat all-take): **{nsv}/{len(finalists)}**.",
     f"- **Bonferroni reality check:** with {TOPK} finalists drawn from {N_SEARCH} searched, expected false "
     "positives at raw 95% CI ≈ several. A survivor is only credible if its lift is LARGE and its CI clears 0 "
     "with margin — a barely-positive CI after this much searching is most likely snooping.",
     "- The all-take baseline on each filter is the honest floor; a real slug-selector must beat it by a wide, "
     "confound-free margin that holds on the lockbox. Read the table with that skepticism.",
     "","Full per-candidate log: `search_log.parquet`. Re-run wider: `python search.py 3000`."]
(ROOT/"strategy_lab"/"reports"/"AUTORESEARCH_SEARCH_RESULTS_2026_06_03.md").write_text("\n".join(L),encoding="utf-8")
pd.DataFrame([{"score":s,**{k:(json.dumps(v) if isinstance(v,(list,dict)) else v) for k,v in c.items()},
               "dev_score":r["score"],"dev_lift":r["lift"],"confound":r["confound"]} for s,c,r in cands]).to_parquet(HERE/"_data"/"search_log.parquet",index=False)
print("\n".join(L[4:]),flush=True)
print(f"\nwrote report + search_log.parquet  ({time.time()-t0:.0f}s, {N_SEARCH} candidates)",flush=True)
