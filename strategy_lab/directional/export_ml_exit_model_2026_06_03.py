"""
Export the P2 exit-timing model as a PORTABLE deploy artifact for the live engine.
Retrains on ALL filled BTC+ETH fires (the methodology was validated on the lockbox; the deploy
model uses all data). Exports:
  - ml_exit_model_2026_06_03.json      (native XGBoost booster — load with xgboost, no sklearn needed)
  - ml_exit_calibrator_2026_06_03.json (isotonic as (x,y) breakpoints -> apply with np.interp)
  - ml_exit_contract_2026_06_03.json   (feature order, threshold, defaults, exit checkpoints, fee)
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT/"strategy_lab"/"directional"/"_results"/"scalp_hedge_physics_cache_2026_06_03.parquet"
OUTD = ROOT/"strategy_lab"/"directional"/"_results"
from xgboost import XGBClassifier
from sklearn.isotonic import IsotonicRegression

CKPTS=[30,45,60,75,90,120]; ALLDT=[30,45,60,75,90,120,150,180]; EPS=0.005
FEATS=["cur","profit","mom","elapsed","entry_vwap","delta_bps","a_BTC","tf_15m","ps","pd_","pds","pmar"]
THRESHOLD=0.60

c=pd.read_parquet(CACHE)
F=c[c.filled & c.asset.isin(["BTC","ETH"])].sort_values("fire_us").reset_index(drop=True)
rows=[]
for r in F.itertuples():
    bids={dt:(getattr(r,f"bid_{dt}") if np.isfinite(getattr(r,f"bid_{dt}")) else np.nan) for dt in ALLDT}
    for c0 in CKPTS:
        cur=bids[c0]
        if not np.isfinite(cur): continue
        pi=ALLDT.index(c0); prev=bids[ALLDT[pi-1]] if pi>0 else r.entry_vwap
        mom=cur-(prev if np.isfinite(prev) else r.entry_vwap)
        fut=[bids[d] for d in ALLDT if d>c0 and np.isfinite(bids[d])]
        y=1 if (fut and max(fut)>cur+EPS) else 0
        rows.append(dict(cur=cur,profit=cur-r.entry_vwap,mom=mom,elapsed=c0,entry_vwap=r.entry_vwap,
                         delta_bps=r.delta_bps,a_BTC=int(r.asset=="BTC"),tf_15m=int(r.tf=="15m"),
                         ps=getattr(r,"phys_speed_abs",np.nan),pd_=getattr(r,"phys_dist_abs",np.nan),
                         pds=getattr(r,"phys_d_speed",np.nan),pmar=getattr(r,"phys_margin",np.nan),y=y))
T=pd.DataFrame(rows)
print(f"train rows={len(T)} hold-rate={100*T.y.mean():.1f}%",flush=True)
m=XGBClassifier(n_estimators=300,max_depth=4,learning_rate=0.04,subsample=0.8,colsample_bytree=0.8,
                min_child_weight=10,reg_lambda=3.0,eval_metric="logloss",tree_method="hist")
m.fit(T[FEATS],T.y)
raw=m.predict_proba(T[FEATS])[:,1]
iso=IsotonicRegression(out_of_bounds="clip"); iso.fit(raw,T.y)
m.get_booster().save_model(str(OUTD/"ml_exit_model_2026_06_03.json"))
json.dump({"x":[float(v) for v in iso.X_thresholds_],"y":[float(v) for v in iso.y_thresholds_]},
          open(OUTD/"ml_exit_calibrator_2026_06_03.json","w"))
defaults={"ps":float(np.nanmedian(T.ps)),"pd_":float(np.nanmedian(T.pd_)),
          "pds":float(np.nanmedian(T.pds)),"pmar":float(np.nanmedian(T.pmar))}
json.dump({"feature_order":FEATS,"threshold":THRESHOLD,"checkpoints_s":CKPTS,"label_eps":EPS,
           "missing_defaults":defaults,"fee_for_eval":0.015,"trained_n":len(T),
           "note":"sell held shares when calibrated P(hold)<threshold at a checkpoint; else hold to resolution"},
          open(OUTD/"ml_exit_contract_2026_06_03.json","w"),indent=2)
# sanity: reproduce a couple predictions
import numpy as np
xb=json.load(open(OUTD/"ml_exit_calibrator_2026_06_03.json"))
p_cal=np.interp(raw[:3],xb["x"],xb["y"])
print("sample raw->cal:",list(zip([round(float(v),3) for v in raw[:3]],[round(float(v),3) for v in p_cal])),flush=True)
print("wrote artifacts to",OUTD,flush=True)
