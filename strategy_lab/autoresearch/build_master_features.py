"""
Assemble the master feature matrix for autoresearch: scalp cache (labels + bid paths + physics) +
TA indicators (asof ws_s) + CLOB flow (per slug). Writes _data/master_features.parquet.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
D = ROOT/"strategy_lab"/"autoresearch"/"_data"
WIN={"5m":300,"15m":900}

cache=pd.read_parquet(ROOT/"strategy_lab"/"directional"/"_results"/"scalp_hedge_physics_cache_2026_06_03.parquet")
fires=pd.read_parquet(ROOT/"strategy_lab"/"lag_taker_fires_oos_2026_06_01.parquet")[["slug","slot_start","tf","segment","direction"]]
clob=pd.read_parquet(D/"clob_flow.parquet")

m=cache.merge(fires,on="slug",how="left",suffixes=("","_f"))
m["ws_s"]=(m.slot_start.astype("float")-m.tf.map(WIN))
# asof-merge indicators per asset at ws_s
ind_cols=None; parts=[]
for asset in ["BTC","ETH","SOL"]:
    sub=m[m.asset==asset].copy()
    sub["ws_s"]=pd.to_numeric(sub["ws_s"],errors="coerce")
    sub=sub.dropna(subset=["ws_s"]).sort_values("ws_s")
    ind=pd.read_parquet(D/f"indicators_{asset.lower()}.parquet")
    ind["ts_s"]=pd.to_numeric(ind["ts_s"],errors="coerce")
    ind=ind.dropna(subset=["ts_s"]).sort_values("ts_s")
    ind_cols=[c for c in ind.columns if c!="ts_s"]
    j=pd.merge_asof(sub, ind, left_on="ws_s", right_on="ts_s", direction="backward")
    parts.append(j)
m=pd.concat(parts,ignore_index=True)
m=m.merge(clob,on="slug",how="left")
clob_cols=[c for c in clob.columns if c!="slug"]
m[clob_cols]=m[clob_cols].fillna(0)

# scalp labels (fee=0.015): pnl at +45 and +60, binary positive, reprice magnitude
def hold07(ev,sh,won): return sh*(1-ev)*(1-0.07*ev) if won else -sh*ev
def scalp(ev,sh,b,won,fee=0.015):
    return hold07(ev,sh,won) if not np.isfinite(b) else (b-ev)*sh-fee*sh*(ev*(1-ev)+b*(1-b))
F=m[m.filled].copy()
F["pnl45"]=[scalp(r.entry_vwap,r.shares,r.bid_45,r.won) for r in F.itertuples()]
F["pnl60"]=[scalp(r.entry_vwap,r.shares,r.bid_60,r.won) for r in F.itertuples()]
F["reprice45"]=F.bid_45 - F.entry_vwap
F["y_scalp_pos"]=(F.pnl45>0).astype(int)
F.to_parquet(D/"master_features.parquet",index=False)
print(f"master_features: n={len(F)} cols={F.shape[1]}",flush=True)
print(f"  indicator feats={len(ind_cols)} clob feats={len(clob_cols)}",flush=True)
print(f"  y_scalp_pos rate={100*F.y_scalp_pos.mean():.1f}%  mean pnl45={F.pnl45.mean():+.3f}",flush=True)
# save the feature-name groups for the harness
import json
json.dump({"indicators":ind_cols,"clob":clob_cols,
           "physics":["phys_speed_abs","phys_dist_abs","phys_speed_away","phys_d_speed","phys_margin","phys_have_m"],
           "entry":["entry_vwap","delta_bps"],"path":["bid_30","bid_45","bid_60","bid_75","bid_90"]},
          open(D/"feature_groups.json","w"),indent=2)
print("wrote feature_groups.json",flush=True)
