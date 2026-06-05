"""
P2 exit-timing model — learned ONLINE exit policy for the scalp.

At each checkpoint c in {30,45,60,75,90,120}s after entry, decide HOLD vs SELL using only
features observable AT c (current bid, profit-so-far, reprice momentum, elapsed, entry context,
physics-at-entry). Label = "does the bid IMPROVE after c" (max future bid > cur). Policy: sell at
the first checkpoint where P(hold-beneficial) < thr; else hold to resolution.

Trained on ALL filled BTC+ETH fires (exit decision is about the path, not the entry filter).
Evaluated vs fixed TIME+45 on a time-held-out lockbox AND the deployed cell. Purged by fire.
Writes EXIT_TIMING_MODEL_2026_06_03.md.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT/"strategy_lab"/"directional"/"_results"/"scalp_hedge_physics_cache_2026_06_03.parquet"
FIRES = ROOT/"strategy_lab"/"lag_taker_fires_oos_2026_06_01.parquet"
OUT = ROOT/"strategy_lab"/"reports"/"EXIT_TIMING_MODEL_2026_06_03.md"
RNG = np.random.default_rng(11)
CKPTS = [30,45,60,75,90,120]; ALLDT=[30,45,60,75,90,120,150,180]
FEE = 0.015
EPS = 0.005   # min improvement to call holding "beneficial"

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
try:
    from xgboost import XGBClassifier; HAVE_XGB=True
except Exception: HAVE_XGB=False

def boot(x,n=8000):
    x=np.asarray(x,float);x=x[np.isfinite(x)]
    if len(x)<3:return(np.nan,np.nan)
    m=x[RNG.integers(0,len(x),size=(n,len(x)))].mean(1);return float(np.percentile(m,2.5)),float(np.percentile(m,97.5))
def tstat(x):
    x=np.asarray(x,float);x=x[np.isfinite(x)];return np.nan if len(x)<3 or x.std(ddof=1)==0 else x.mean()/(x.std(ddof=1)/np.sqrt(len(x)))
def hold07(ev,sh,won): return sh*(1-ev)*(1-0.07*ev) if won else -sh*ev
def sell_pnl(ev,sh,b,won,fee=FEE):
    if not np.isfinite(b): return hold07(ev,sh,won)
    return (b-ev)*sh - fee*sh*(ev*(1-ev)+b*(1-b))
def fit_model():
    if HAVE_XGB:
        return XGBClassifier(n_estimators=300,max_depth=4,learning_rate=0.04,subsample=0.8,
                             colsample_bytree=0.8,min_child_weight=10,reg_lambda=3.0,
                             eval_metric="logloss",tree_method="hist")
    return HistGradientBoostingClassifier(max_depth=4,learning_rate=0.04,max_iter=300,l2_regularization=3.0,min_samples_leaf=40)

c = pd.read_parquet(CACHE)
seg = pd.read_parquet(FIRES)[["slug","fire_us","segment"]]
c = c.merge(seg,on=["slug","fire_us"],how="left")
F = c[c.filled & c.asset.isin(["BTC","ETH"])].sort_values("fire_us").reset_index(drop=True)
print(f"filled BTC+ETH fires={len(F)}",flush=True)
have_phys = "phys_speed_abs" in F.columns

# ---- build checkpoint-level training rows ----
def bidcol(r,dt):
    v=getattr(r,f"bid_{dt}"); return v if np.isfinite(v) else np.nan
rows=[];
for fi,r in enumerate(F.itertuples()):
    bids={dt:bidcol(r,dt) for dt in ALLDT}
    for ci,c0 in enumerate(CKPTS):
        cur=bids[c0]
        if not np.isfinite(cur): continue
        prevdt = ALLDT[ALLDT.index(c0)-1] if ALLDT.index(c0)>0 else None
        prev = bids[prevdt] if prevdt else r.entry_vwap
        mom = cur - (prev if np.isfinite(prev) else r.entry_vwap)
        fut=[bids[d] for d in ALLDT if d>c0 and np.isfinite(bids[d])]
        fmax=max(fut) if fut else -1
        y = 1 if (fmax > cur + EPS) else 0
        feat=dict(fire=fi, ckpt=c0, cur=cur, profit=cur-r.entry_vwap, mom=mom, elapsed=c0,
                  entry_vwap=r.entry_vwap, delta_bps=r.delta_bps,
                  a_BTC=int(r.asset=="BTC"), tf_15m=int(r.tf=="15m"), y=y)
        if have_phys:
            feat.update(ps=getattr(r,"phys_speed_abs",np.nan), pd_=getattr(r,"phys_dist_abs",np.nan),
                        pds=getattr(r,"phys_d_speed",np.nan), pmar=getattr(r,"phys_margin",np.nan))
        rows.append(feat)
T=pd.DataFrame(rows)
FEATS=["cur","profit","mom","elapsed","entry_vwap","delta_bps","a_BTC","tf_15m"]+(["ps","pd_","pds","pmar"] if have_phys else [])
print(f"checkpoint rows={len(T)}  hold-beneficial rate={100*T.y.mean():.1f}%",flush=True)

# ---- time-split by FIRE (lockbox = last 25% of fires) ----
nfire=len(F); cut=int(nfire*0.75)
dev_fires=set(range(cut)); lock_fires=set(range(cut,nfire))
dev=T[T.fire.isin(dev_fires)];
mod=fit_model(); mod.fit(dev[FEATS], dev.y)
cal=dev.iloc[-min(2000,len(dev)):]
iso=IsotonicRegression(out_of_bounds="clip"); iso.fit(mod.predict_proba(cal[FEATS])[:,1], cal.y)
T["phold"]=iso.transform(mod.predict_proba(T[FEATS])[:,1])

def policy_pnl(fire_ids, thr):
    """For each fire: sell at first ckpt where phold<thr; else hold to resolution."""
    out=[]; exits=[]
    for fi in fire_ids:
        r=F.iloc[fi]; sub=T[T.fire==fi].sort_values("ckpt")
        sold=None
        for rr in sub.itertuples():
            if rr.phold < thr:
                sold=(rr.ckpt, rr.cur); break
        if sold is None:
            out.append(hold07(r.entry_vwap,r.shares,r.won)); exits.append(999)
        else:
            out.append(sell_pnl(r.entry_vwap,r.shares,sold[1],r.won)); exits.append(sold[0])
    return np.array(out), np.array(exits)

def fixed_pnl(fire_ids, dt):
    return np.array([sell_pnl(F.iloc[fi].entry_vwap,F.iloc[fi].shares,
                              getattr(F.iloc[fi],f"bid_{dt}"),F.iloc[fi].won) for fi in fire_ids])

# pick thr on dev maximizing mean policy pnl
dev_ids=list(dev_fires)
best=None
for thr in np.round(np.arange(0.2,0.85,0.05),2):
    p,_=policy_pnl(dev_ids,thr)
    if best is None or p.mean()>best[1]: best=(thr,p.mean())
THR=best[0]
print(f"dev best thr={THR} dev policy $/tr={best[1]:+.3f}",flush=True)

def report(name, ids):
    pol,ex=policy_pnl(ids,THR); f45=fixed_pnl(ids,45); f60=fixed_pnl(ids,60)
    def line(tag,p):
        ci=boot(p); return f"| {tag} | {len(p)} | {p.mean():+.3f} | {tstat(p):.2f} | [{ci[0]:+.2f},{ci[1]:+.2f}] |"
    L=[f"### {name} (n_fire={len(ids)})","","| policy | n | $/tr | t | CI |","|---|--:|--:|--:|--:|",
       line("fixed TIME+45",f45), line("fixed TIME+60",f60), line(f"MODEL policy (thr={THR})",pol)]
    diff=pol.mean()-f45.mean()
    L.append(f"\nmodel − fixed45 = {diff:+.3f}/tr.  exit-time dist: "+
             ", ".join(f"{d}s:{int((ex==d).sum())}" for d in CKPTS)+f", hold:{int((ex==999).sum())}")
    return L, pol, f45

lock_ids=list(lock_fires)
dep = F.reset_index().query("asset in ['BTC','ETH'] and delta_bps>=5 and entry_vwap<0.55")["index"].tolist()
dep_lock=[i for i in dep if i in lock_fires]

allL=["# P2 Exit-Timing Model — learned online exit policy — 2026-06-03","",
 f"Model={'XGBoost' if HAVE_XGB else 'HistGB'}. Online HOLD-vs-SELL at checkpoints {CKPTS}s. "
 f"Features (causal at ckpt): {FEATS}. Label=bid improves after ckpt (+{EPS}). Sell when P(hold)<thr. "
 f"Trained on all filled BTC+ETH fires; lockbox=last 25% of fires by time. fee={FEE}.",""]
for nm,ids in [("LOCKBOX (all)",lock_ids),("LOCKBOX deployed cell (δ≥5,vwap<0.55)",dep_lock),
               ("FULL deployed cell (in+out)",dep)]:
    if len(ids)<5:
        allL+= [f"### {nm}: n={len(ids)} too few",""]; continue
    rl,pol,f45=report(nm,ids); allL+=rl+[""]
# feature importance (xgb)
if HAVE_XGB:
    try:
        imp=sorted(zip(FEATS,mod.feature_importances_),key=lambda x:-x[1])[:8]
        allL+=["## Top features", ", ".join(f"{k}={v:.3f}" for k,v in imp),""]
    except Exception: pass
allL+=["## Read","- Oracle best-exit ceiling was +$18.5/tr (vs fixed +45 ≈ +$5.6). This model tries to close that gap.",
 "- If MODEL ≈ fixed45 → the early path carries no exploitable timing signal beyond 'exit fast'; keep fixed +45.",
 "- If MODEL > fixed45 with lockbox CI>0 → deploy as a dynamic exit policy (shadow first)."]
OUT.write_text("\n".join(allL),encoding="utf-8")
print("\n".join(allL),flush=True)
print("\nwrote",OUT,flush=True)
