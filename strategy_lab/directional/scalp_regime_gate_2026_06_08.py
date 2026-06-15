"""
THREAD B — REGIME GATES on the exit-scalp (when is the edge strongest?). NOT a directional predictor.
Pre-registered regime features (avoid the 4.8M-sweep overfit trap): realized-vol, short-trend, long-trend,
session(control, already-validated), delta(baseline/sizer). Bucket gated-scalp $/tr by tercile + bootstrap CI.
Discipline: train/test split (BTC+ETH train, SOL test AND time-split) — a gate only counts if it holds OOS.
Input: scalp_oos_bbo_fires_2026_06_05*.parquet (953 gated fires, Mar30-Apr21) + klines_1s.
NOTE: funding/OI regime NOT testable here (cex_futures only May30+); deferred to recent shadow data.
"""
import sys, warnings, glob
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
CANON = ROOT / "data/v4/canonical"
RES = ROOT / "strategy_lab/directional/_results"

# pool all saved OOS gated fires (btc/eth/sol + doge/bnb + xrp)
fires = pd.concat([pd.read_parquet(f) for f in glob.glob(str(RES/"scalp_oos_bbo_fires_2026_06_05*.parquet"))], ignore_index=True)
fires = fires.drop_duplicates(["coin","fire_us"]).reset_index(drop=True)
print(f"pooled gated OOS fires: {len(fires)}  coins={fires.coin.value_counts().to_dict()}")

def klines(coin):
    sym=f"BINANCE_SPOT_{coin.upper()}_USDT"
    df=pd.read_parquet(CANON/"klines_1s.parquet", columns=["symbol_id","time_period_start_us","price_close"],
                       filters=[("symbol_id","==",sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)

# regime features per fire
def add_regime(g):
    coin=g.name; te,pe=klines(coin)
    lp=np.log(pe)
    out=[]
    for fu in g.fire_us.values:
        i=np.searchsorted(te,int(fu),"right")-1
        if i<310: out.append((np.nan,np.nan,np.nan)); continue
        # realized vol: std of 1s log-returns over trailing 300s
        seg=lp[i-300:i+1]; rv=np.std(np.diff(seg))*1e4 if len(seg)>2 else np.nan
        # short trend: 900s return bps; long trend: 3600s return bps (abs = trend strength, sign = dir)
        tr9=(pe[i]/pe[i-900]-1)*1e4 if i>=900 else np.nan
        tr36=(pe[i]/pe[i-3600]-1)*1e4 if i>=3600 else np.nan
        out.append((rv,tr9,tr36))
    a=np.array(out)
    return pd.DataFrame({"rv300":a[:,0],"tr900":a[:,1],"tr3600":a[:,2]}, index=g.index)

reg=fires.groupby("coin",group_keys=False).apply(add_regime)
F=pd.concat([fires,reg],axis=1).dropna(subset=["rv300","tr900","tr3600"])
F["abs_tr900"]=F.tr900.abs(); F["abs_tr3600"]=F.tr3600.abs()
print(f"fires with regime features: {len(F)}")

def boot(v,nb=5000):
    v=np.asarray(v)
    if len(v)<5: return (np.nan,np.nan)
    i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def cell(v):
    v=np.asarray(v)
    if len(v)<5: return f"n={len(v):4d} (few)"
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else np.nan; lo,hi=boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={ (v>0).mean():.2f}"

def by_tercile(df, feat, label):
    print(f"\n--- {label} ({feat}) terciles ---")
    q=df[feat].quantile([1/3,2/3]).values
    df=df.assign(_b=np.where(df[feat]<=q[0],"LOW",np.where(df[feat]<=q[1],"MID","HIGH")))
    for b in ["LOW","MID","HIGH"]:
        print(f"  {b:4s} {cell(df[df._b==b].pnl60.values)}")
    return q

print(f"\n===== BASELINE (all gated pooled) =====\n  {cell(F.pnl60.values)}")
print("\n===== REGIME BUCKETS (pooled) =====")
for feat,lab in [("rv300","realized vol 300s"),("abs_tr900","|trend| 900s"),("abs_tr3600","|trend| 3600s"),
                 ("delta","delta_bps (baseline sizer)")]:
    by_tercile(F,feat,lab)
# session control (already validated)
print("\n--- session (control) ---")
print(f"  22-02 UTC   {cell(F[F.hour.isin([22,23,0,1])].pnl60.values)}")
print(f"  excl {{12,17}} {cell(F[~F.hour.isin([12,17])].pnl60.values)}")
print(f"  dead {{12,17}} {cell(F[F.hour.isin([12,17])].pnl60.values)}")

# cross: vol x trend
print("\n===== CROSS: realized-vol x |trend900| (pooled) =====")
qv=F.rv300.quantile([.5]).values[0]; qt=F.abs_tr900.quantile([.5]).values[0]
for vl,vsel in [("loVol",F.rv300<=qv),("hiVol",F.rv300>qv)]:
    for tl,tsel in [("loTrend",F.abs_tr900<=qt),("hiTrend",F.abs_tr900>qt)]:
        print(f"  {vl}/{tl}: {cell(F[vsel&tsel].pnl60.values)}")

# TRAIN/TEST discipline: pick best single-feature gate on TRAIN, check it holds on TEST
print("\n===== TRAIN/TEST (gate must hold OOS) =====")
F=F.sort_values("fire_us"); half=F.fire_us.median()
tr=F[F.fire_us<=half]; te=F[F.fire_us>half]
print(f"  time-split train n={len(tr)} test n={len(te)}")
# candidate gate: HIGH realized vol (hypothesis: lag edge bigger when vol high)
for name,sel_tr,sel_te in [
    ("hiVol(>train median rv)", tr.rv300>tr.rv300.median(), te.rv300>tr.rv300.median()),
    ("hiTrend900(>train med)", tr.abs_tr900>tr.abs_tr900.median(), te.abs_tr900>tr.abs_tr900.median()),
    ("hiDelta(>train med)", tr.delta>tr.delta.median(), te.delta>tr.delta.median()),
]:
    print(f"  GATE {name}")
    print(f"    TRAIN {cell(tr[sel_tr].pnl60.values)}")
    print(f"    TEST  {cell(te[sel_te].pnl60.values)}")
print("\nREAD: a regime gate is REAL only if it lifts $/tr above baseline on BOTH train and test (CI>0).")
print("CAVEAT: BBO top-of-book fill (optimistic); SOL fires thin. funding/OI regime NOT in this window.")
