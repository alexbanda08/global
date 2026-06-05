"""
autoresearch FITNESS — evaluates a slug-selection / scalp candidate on the master feature matrix.
The single metric an agent optimizes. Bakes in this project's trap-antibodies:
  - label = scalp PnL-after-fee (NOT outcome/WR/AUC)
  - purged time-held-out LOCKBOX (last 25% by fire_us) — never trained on
  - bootstrap CI; fitness rewards CI>0, penalizes CI straddling 0
  - per-asset breakdown to expose asset-confounds
  - bid_* path columns are FORBIDDEN as features (they ARE the label) — auto-stripped
Returns a dict; `fitness` scalar = lockbox gated $/tr lower-CI (conservative).
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
D = ROOT/"strategy_lab"/"autoresearch"/"_data"
RNG = np.random.default_rng(17)
FORBIDDEN = {"pnl45","pnl60","reprice45","y_scalp_pos","won","bid_30","bid_45","bid_60","bid_75",
             "bid_90","bid_120","bid_150","bid_180","bid_pathmax","bid_pathmax_dt","shares",
             "tp_hit_60_dt","tp_hit_65_dt","tp_hit_70_dt","tp_hit_75_dt","opp_ask_min","oppask_30",
             "oppask_60","oppask_90","orig_vwap","filled"}
GROUPS = json.load(open(D/"feature_groups.json"))

def _boot_ci(x,n=8000):
    x=np.asarray(x,float); x=x[np.isfinite(x)]
    if len(x)<3: return (np.nan,np.nan)
    m=x[RNG.integers(0,len(x),size=(n,len(x)))].mean(1)
    return float(np.percentile(m,2.5)),float(np.percentile(m,97.5))

def resolve_features(spec):
    feats=[]
    for s in spec:
        if s in GROUPS: feats+=GROUPS[s]
        else: feats.append(s)
    return [f for f in dict.fromkeys(feats) if f not in FORBIDDEN]

def score_candidate(cand, df=None):
    if df is None: df=pd.read_parquet(D/"master_features.parquet")
    df=df.sort_values("fire_us").reset_index(drop=True)
    # entry filter
    ef=cand.get("entry_filter")
    if ef=="deployed": df=df[(df.asset.isin(["BTC","ETH"]))&(df.delta_bps>=5)&(df.entry_vwap<0.55)]
    elif ef=="vwap055": df=df[(df.asset.isin(["BTC","ETH"]))&(df.entry_vwap<0.55)]
    elif ef=="d3vwap055": df=df[(df.asset.isin(["BTC","ETH"]))&(df.delta_bps>=3)&(df.entry_vwap<0.55)]
    else: df=df[df.asset.isin(["BTC","ETH"])]
    df=df.reset_index(drop=True)
    exit_col=f"bid_{cand.get('exit_dt',45)}"
    pnl = np.where(np.isfinite(df[exit_col]), (df[exit_col]-df.entry_vwap)*df.shares
                   - 0.015*df.shares*(df.entry_vwap*(1-df.entry_vwap)+df[exit_col]*(1-df[exit_col])),
                   np.where(df.won, df.shares*(1-df.entry_vwap)*(1-0.07*df.entry_vwap), -df.shares*df.entry_vwap))
    pnl=np.asarray(pnl,float)
    n=len(df); cut=int(n*0.75)
    feats=resolve_features(cand["features"])
    feats=[f for f in feats if f in df.columns]
    X=df[feats].astype(float).fillna(0.0).values
    y=(pnl>0).astype(int)
    res={"candidate":cand.get("name","?"),"n":n,"n_lock":n-cut,"features_used":len(feats),
         "entry_filter":ef or "broad","exit_dt":cand.get("exit_dt",45)}
    # model
    mt=cand.get("model","xgb")
    if cut<150 or len(np.unique(y[:cut]))<2:
        res.update(fitness=-99,note="too few dev rows"); return res
    if mt=="xgb":
        from xgboost import XGBClassifier
        mdl=XGBClassifier(n_estimators=cand.get("n_est",250),max_depth=cand.get("depth",4),
                          learning_rate=0.04,subsample=0.8,colsample_bytree=0.8,min_child_weight=8,
                          reg_lambda=3.0,eval_metric="logloss",tree_method="hist")
    elif mt=="rf":
        from sklearn.ensemble import RandomForestClassifier
        mdl=RandomForestClassifier(n_estimators=300,max_depth=cand.get("depth",6),min_samples_leaf=20,n_jobs=-1)
    elif mt=="logit":
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import make_pipeline
        mdl=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500,C=cand.get("C",0.5)))
    else:
        res.update(fitness=-99,note=f"unknown model {mt}"); return res
    from sklearn.isotonic import IsotonicRegression
    mdl.fit(X[:cut],y[:cut])
    praw=mdl.predict_proba(X)[:,1]
    iso=IsotonicRegression(out_of_bounds="clip"); cal=slice(max(0,cut-1500),cut)
    iso.fit(praw[cal],y[cal]); p=iso.transform(praw)
    # gate: pick threshold on DEV maximizing dev gated pnl (>=40 taken)
    best=None
    for thr in np.round(np.arange(0.40,0.75,0.025),3):
        tk=p[:cut]>thr
        if tk.sum()<40: continue
        mu=pnl[:cut][tk].mean()
        if best is None or mu>best[1]: best=(thr,mu)
    THR=best[0] if best else 0.5
    lock=slice(cut,n)
    take=p[lock]>THR
    allp=pnl[lock]; gp=allp[take]
    res["threshold"]=THR
    res["all_dpt"]=round(float(allp.mean()),3); res["all_ci"]=tuple(round(v,3) for v in _boot_ci(allp))
    res["gated_n"]=int(take.sum())
    if take.sum()>=20:
        ci=_boot_ci(gp)
        res["gated_dpt"]=round(float(gp.mean()),3); res["gated_ci"]=tuple(round(v,3) for v in ci)
        res["lift"]=round(float(gp.mean()-allp.mean()),3)
        # per-asset confound check on the gated set
        la=df.iloc[cut:].reset_index(drop=True)
        mix={a:int(((la.asset==a)&take).sum()) for a in ["BTC","ETH"]}
        res["gated_asset_mix"]=mix
        # universe has both assets? then a gate that keeps >90% one asset is an ASSET-SELECTION CONFOUND
        uni_assets=set(df.asset.unique()); tot=sum(mix.values()) or 1
        confound = (len({a for a in ["BTC","ETH"] if a in uni_assets})>1) and (min(mix.values())/tot < 0.10)
        res["asset_confound"]=bool(confound)
        # fitness: conservative lower-CI of gated, MUST beat all-take; confound -> heavy penalty
        base=float(ci[0]) if ci[0]>res["all_ci"][0] else min(float(ci[0]),0.0)
        res["fitness"]=round(base-3.0,3) if confound else round(base,3)
    else:
        res.update(gated_n=int(take.sum()),fitness=-9,note="gate too tight (lockbox n<20)")
    return res

if __name__=="__main__":
    import candidate
    print(json.dumps(score_candidate(candidate.CANDIDATE),indent=2,default=str))
