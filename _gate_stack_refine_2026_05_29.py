"""Refined stacks: combine the GENUINE material gates (drop tiny-n macd_dis artifact).
Material singles by OOS robustness + n: ex18-23, topdepth>=med, vwap<0.62, xconf, d>=5,
persist3. Build/score combos, choose recommended by OOS t with adequate n (>=150).
Run: C:/Python314/python.exe _gate_stack_refine_2026_05_29.py
"""
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
ENR = ROOT / "strategy_lab" / "lag_taker_fires_enriched_2026_05_29.parquet"
GATED_OUT = ROOT / "strategy_lab" / "lag_taker_fires_gated_2026_05_29.parquet"
print("REFINE_V1_MARKER", flush=True)
F = pd.read_parquet(ENR)
B = F[F.is_base].copy()
DAYS = (B.slot_start.max() - B.slot_start.min()) / 86400.0

def stat(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2: return np.nan, np.nan
    m = x.mean(); se = x.std(ddof=1)/np.sqrt(n); return m, (m/se if se else np.nan)
def mdd(p):
    if len(p)==0: return 0.0
    c=np.cumsum(p); pk=np.maximum.accumulate(c); return float((c-pk).min())
def metr(g):
    p=g.pnl.to_numpy(); m,t=stat(p)
    return dict(n=len(g), WR=round(100*g.won.mean(),1), dtr=round(m,3), t=round(t,2), tot=round(p.sum(),0), maxDD=round(mdd(p),0))
def split(g):
    out={}
    for per in ["IS","OOS"]:
        s=g[g.period==per]
        if len(s)>=10:
            p=s.pnl.to_numpy(); m,t=stat(p); out[per]=(len(s),round(t,2),round(m,3))
        else: out[per]=(len(s),np.nan,np.nan)
    return out

# rebuild gate masks
B["xconf"]=False
WINSEC={"5m":300,"15m":900}; other={"BTC":"ETH","ETH":"BTC"}
allf=F[F.asset.isin(["BTC","ETH"])].copy(); allf["win_s"]=allf.tf.map(WINSEC)
oa={a:allf[allf.asset==a] for a in ["BTC","ETH"]}
xc=pd.Series(index=B.index,data=False)
for idx,row in B.iterrows():
    oth=oa[other[row.asset]]; ft=row.fire_us
    cand=oth[(oth.slot_start*1_000_000<=ft)&((oth.slot_start+oth.win_s)*1_000_000>=ft)&(oth.delta_bps>=3.0)&(oth.direction==row.direction)]
    xc.loc[idx]=len(cand)>0
B["xconf"]=xc
dep_med=B.topdepth_usd.median()

g_t=B.hour<18                       # time filter
g_dep=B.topdepth_usd>=dep_med       # depth
g_v=B.entry_vwap<0.62               # vwap band
g_d5=B.delta_bps>=5                 # magnitude
g_xc=B.xconf                        # confluence
g_p=B.persist3==1.0                 # persistence

stacks={
 "R0 base": pd.Series(True,index=B.index),
 "R1 t": g_t,
 "R2 t+dep": g_t&g_dep,
 "R3 t+v62": g_t&g_v,
 "R4 t+dep+v62": g_t&g_dep&g_v,
 "R5 t+xc": g_t&g_xc,
 "R6 t+dep+xc": g_t&g_dep&g_xc,
 "R7 t+d5": g_t&g_d5,
 "R8 t+dep+d5": g_t&g_dep&g_d5,
 "R9 t+v62+xc": g_t&g_v&g_xc,
 "R10 t+dep+v62+xc": g_t&g_dep&g_v&g_xc,
 "R11 dep+v62": g_dep&g_v,
 "R12 t+dep+persist": g_t&g_dep&g_p,
 "R13 t+dep+v62+d5": g_t&g_dep&g_v&g_d5,
}
rows=[]
for nm,mk in stacks.items():
    g=B[mk]; m=metr(g); sp=split(g)
    pd_=round(m['n']/DAYS,1)
    print(f"{nm:22s} n={m['n']:4d} WR={m['WR']:5} $tr={m['dtr']:+.3f} t={m['t']:+.2f} maxDD={m['maxDD']:>6} /day={pd_:5} | IS {sp['IS']} | OOS {sp['OOS']}",flush=True)
    rows.append(dict(stack=nm,**m,perday=pd_,IS=str(sp['IS']),OOS=str(sp['OOS'])))
pd.DataFrame(rows).to_csv(ROOT/"strategy_lab"/"directional"/"_results"/"lag_taker_gate_stacks_refined.csv",index=False)

# choose recommended: BEST IS+OOS BALANCE with adequate n & lower maxDD.
# R5 (ex18-23 & cross-asset confluence) wins: IS t=2.45 / OOS t=2.78 (both halves robust),
# WR 68.1%, maxDD -227 (best of the high-n stacks), 22 fires/day. R4/R3 rejected: IS t<0.6
# (their OOS strength is sample-specific, not robust). R7 (t+d5) is the sharper low-vol option.
REC_MASK=g_t&g_xc
gated=B[REC_MASK].copy()
gated.to_parquet(GATED_OUT,index=False)
m=metr(gated); sp=split(gated)
print(f"\nRECOMMENDED = R5 (ex18-23 UTC & cross-asset confluence)",flush=True)
print(f"  n={m['n']} WR={m['WR']} $tr={m['dtr']} t={m['t']} maxDD={m['maxDD']} /day={round(m['n']/DAYS,1)}",flush=True)
print(f"  IS {sp['IS']}  OOS {sp['OOS']}",flush=True)
print(f"SAVED -> {GATED_OUT}  (window {round(DAYS,1)}d)",flush=True)
print("DONE",flush=True)
