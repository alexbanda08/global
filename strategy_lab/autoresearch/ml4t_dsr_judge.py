"""
ml4t STEP 1 — re-judge the overnight winners under DEFLATED SHARPE (effective_trials = real #searched).
Answers: do ANY of the 387k-searched scalp/slug selectors survive multiple-testing correction? And does the
pre-committed exit-scalp itself pass DSR?

Reconstructs each finalist's gated per-trade win07 PnL on the held-out lockbox, then deflated_sharpe_ratio.
Writes ML4T_DSR_JUDGE_2026_06_04.md.
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE=Path(__file__).resolve().parent; ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio, deflated_sharpe_ratio_from_statistics

m=pd.read_parquet(HERE/"_data"/"master_features.parquet").sort_values("fire_us").reset_index(drop=True)
m=m[m.asset.isin(["BTC","ETH"])].reset_index(drop=True)
fin=json.load(open(HERE/"_data"/"overnight"/"finalists.json")); NT=fin["searched"]; cands=fin["finalists"]
# estimate cross-sectional Sharpe variance across the searched candidates (from the kept top_checkpoint)
try:
    tc=pd.read_parquet(HERE/"_data"/"overnight"/"top_checkpoint.parquet")
    SR_FACTOR=0.635/5.56  # per-trade Sharpe per $/tr (from exit-scalp baseline)
    VAR_TRIALS=float((tc["cv_mean"].astype(float)*SR_FACTOR).var())
except Exception:
    VAR_TRIALS=0.05
print(f"variance_trials(est)={VAR_TRIALS:.4f}",flush=True)

def filt(d,f):
    if f=="vwap055": return d[d.entry_vwap<0.55]
    if f=="d3v055": return d[(d.delta_bps>=3)&(d.entry_vwap<0.55)]
    if f=="d5v055": return d[(d.delta_bps>=5)&(d.entry_vwap<0.55)]
    return d
def pnl_at(d,e):
    b=d[f"bid_{e}"].values; ev=d.entry_vwap.values; sh=d.shares.values; won=d.won.values
    return np.where(np.isfinite(b),(b-ev)*sh-0.015*sh*(ev*(1-ev)+b*(1-b)),
                    np.where(won,sh*(1-ev)*(1-0.07*ev),-sh*ev))
def mk(model,depth):
    if model=="xgb": return XGBClassifier(n_estimators=180,max_depth=depth,learning_rate=0.05,subsample=0.8,colsample_bytree=0.8,min_child_weight=8,reg_lambda=3.0,eval_metric="logloss",tree_method="hist",verbosity=0)
    if model=="rf": return RandomForestClassifier(n_estimators=200,max_depth=depth,min_samples_leaf=20,n_jobs=-1)
    if model=="et": return ExtraTreesClassifier(n_estimators=200,max_depth=depth,min_samples_leaf=20,n_jobs=-1)
    return make_pipeline(StandardScaler(),LogisticRegression(max_iter=400,C=0.5))

def gated_lockbox_pnl(c):
    d=filt(m,c["filter"]).reset_index(drop=True); n=len(d)
    if n<200: return None
    feats=[f for f in c["features"] if f in d.columns]
    X=d[feats].astype(float).fillna(0).values; pnl=pnl_at(d,c["exit_dt"]); y=(pnl>0).astype(int)
    c1=int(n*0.6); c2=int(n*0.75)
    if len(np.unique(y[:c1]))<2: return None
    mdl=mk(c["model"],c["depth"]); mdl.fit(X[:c1],y[:c1])
    ptr=mdl.predict_proba(X[:c1])[:,1]; best=None
    for thr in np.arange(0.42,0.7,0.02):
        tk=ptr>thr
        if tk.sum()<30: continue
        mu=pnl[:c1][tk].mean()
        if best is None or mu>best[1]: best=(thr,mu)
    thr=best[0] if best else 0.5
    plk=mdl.predict_proba(X[c2:])[:,1]; take=plk>thr
    if take.sum()<12: return None
    return pnl[c2:][take]

def dsr_deflated(pnl_arr, ntrials):
    r=np.asarray(pnl_arr,float)/25.0
    if len(r)<5 or r.std()==0: return dict(n=len(r),err="too few")
    sh=float(r.mean()/r.std())
    def _sig(v):
        try: return bool(deflated_sharpe_ratio_from_statistics(observed_sharpe=sh,n_samples=len(r),n_trials=int(ntrials),variance_trials=v,frequency="daily").is_significant)
        except Exception: return None
    try:
        res=deflated_sharpe_ratio_from_statistics(observed_sharpe=sh, n_samples=len(r), n_trials=int(ntrials),
                                                  variance_trials=VAR_TRIALS, frequency="daily")
        return dict(n=len(r), mean_pnl=round(float(np.mean(pnl_arr)),3), sharpe=round(sh,3),
                    prob=round(float(res.probability),3), sig=bool(res.is_significant), sig_cons=_sig(VAR_TRIALS*4))
    except Exception as e:
        return dict(n=len(r), sharpe=round(sh,3), err=str(e)[:50])

def dsr_raw(pnl_arr):
    r=np.asarray(pnl_arr,float)/25.0
    if len(r)<5 or r.std()==0: return dict(n=len(r),err="too few")
    res=deflated_sharpe_ratio(r, frequency="daily")
    return dict(n=len(r), mean_pnl=round(float(np.mean(pnl_arr)),3), sharpe=round(float(res.sharpe_ratio),3),
                prob=round(float(res.probability),3), sig=bool(res.is_significant))

L=["# ml4t Step 1 — Deflated-Sharpe re-judgment of overnight winners — 2026-06-04","",
   f"DSR with `effective_trials` = real #searched. A candidate is REAL only if `is_significant=True` AFTER deflation.",""]

# (A) the 50 scalp/slug finalists (searched 387,200)
L+= [f"## (A) CPU scalp/slug finalists — effective_trials={NT:,}, variance_trials(est)={VAR_TRIALS:.4f}","",
     "| rank | model/filter/exit | n | mean $/tr | Sharpe | DSR prob | sig(estV) | sig(4×V cons) |","|--:|---|--:|--:|--:|--:|:--:|:--:|"]
nsurv=0; ncons=0
for i,c in enumerate(cands[:20]):
    p=gated_lockbox_pnl(c)
    if p is None: L.append(f"| {i+1} | {c['model']}/{c['filter']}/e{c['exit_dt']} | <12 | — | — | — | n/a | n/a |"); continue
    r=dsr_deflated(p,NT); sig="✅" if r.get("sig") else "—"; sc="✅" if r.get("sig_cons") else "—"
    nsurv+= 1 if r.get("sig") else 0; ncons+= 1 if r.get("sig_cons") else 0
    L.append(f"| {i+1} | {c['model']}/{c['filter']}/e{c['exit_dt']} | {r['n']} | {r.get('mean_pnl')} | {r.get('sharpe')} | {r.get('prob')} | {sig} | {sc} |")
L+= ["",f"**Survivors: {nsurv}/20 at estimated variance_trials; {ncons}/20 at 4× (conservative).**",""]

# (B) the pre-committed EXIT-SCALP (NOT searched -> effective_trials=1) on the deployed cell
L+= ["## (B) Pre-committed EXIT-SCALP (deployed cell, NOT searched → effective_trials=1)",""]
D=m[(m.delta_bps>=5)&(m.entry_vwap<0.55)]
for exit_dt,lbl in [(45,"TIME+45"),(60,"TIME+60")]:
    p=pnl_at(D,exit_dt)
    r=dsr_raw(p)
    L.append(f"- {lbl} hold (n={r['n']}): mean ${r.get('mean_pnl')}/tr, per-trade Sharpe {r.get('sharpe')}, "
             f"DSR prob {r.get('prob')}, significant={'✅' if r.get('sig') else '—'}")
L+= ["","## Read",
     "- (A) If 0/20 finalists survive DSR at 387k trials → the scalp/slug SELECTION was multiple-testing noise "
     "(expected — confirms the overnight caution). The selector edge is not real.",
     "- (B) The exit-scalp is pre-registered (not searched) so DSR at trials=1 is the honest test of the LIVE edge. "
     "If significant → the edge survives formal DSR (strong). This is the thing to push to the different-window OOS.",
     "- per-trade Sharpe here is on $25 single-fire returns (high variance); DSR `probability` is the deflated PSR."]
out=ROOT/"strategy_lab"/"reports"/"ML4T_DSR_JUDGE_2026_06_04.md"
out.write_text("\n".join(L),encoding="utf-8"); print("\n".join(L),flush=True); print("\nwrote",out,flush=True)
