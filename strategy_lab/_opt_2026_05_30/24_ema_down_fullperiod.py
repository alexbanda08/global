"""
24 — Full-period backtest btc_15m_ema50_ema800_off600_down (Apr24-May26) + entry-price edge.
Reconstruct: direction=DOWN & g_tr_above_ema50 & g_tr_above_ema800 & offset=600. 0.07-curve, $5.
Confirms whether the cheap-entry edge persists beyond the live window.
"""
import pandas as pd, numpy as np, os
RES=r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results"
df=pd.read_parquet(os.path.join(RES,"sniper_btc15m_v8_gated.parquet"))
m=(df.direction=="DOWN") & df["g_tr_above_ema50"].fillna(False) & df["g_tr_above_ema800"].fillna(False) & (df.fire_offset_s==600)
f=df[m].copy()
f["entry"]=f["entry_vwap"].astype(float)
sh=5.0/f.entry.clip(1e-3)
f["pnl"]=np.where(f.won.astype(bool), sh*(1-f.entry)*(1-0.07*f.entry), -sh*f.entry)
f["d"]=pd.to_datetime(f.fire_us,unit="us"); f["wk"]=f.d.dt.isocalendar().week.astype(int)
print(f"=== FULL-PERIOD (Apr24-May26)  n={len(f)} WR={100*f.won.mean():.1f}% total=${f.pnl.sum():.1f} mean=${f.pnl.mean():.3f} ===")
print("entry dist:", f.entry.describe(percentiles=[.05,.1,.25,.5,.75,.9]).round(3).to_dict())
bins=[0,0.15,0.30,0.50,0.70,0.85,0.95,1.01]
f["bkt"]=pd.cut(f.entry,bins=bins)
g=f.groupby("bkt",observed=True).agg(n=("won","size"),wr=("won",lambda x:round(100*x.mean(),1)),
    mean_entry=("entry",lambda x:round(x.mean(),3)),mean_pnl=("pnl",lambda x:round(x.mean(),3)),
    total=("pnl",lambda x:round(x.sum(),1))).reset_index()
g["implied%"]=(g.mean_entry*100).round(1); g["edge_pp"]=(g.wr-g["implied%"]).round(1)
print("\n=== ENTRY BUCKETS (full period) ==="); print(g.to_string(index=False))
print("\n=== ENTRY FLOOR sweep ===")
for fl in [0.0,0.15,0.30,0.50,0.70]:
    s=f[f.entry>=fl]; print(f"  entry>= {fl:.2f}: n={len(s):4d} WR={100*s.won.mean():.1f}% total=${s.pnl.sum():8.1f} mean=${s.pnl.mean():.3f}")
print("\n=== SKIP the no-edge 0.70-0.85 bucket ===")
keep=f[~f.entry.between(0.70,0.85)]; print(f"  drop 0.70-0.85: n={len(keep)} WR={100*keep.won.mean():.1f}% total=${keep.pnl.sum():.1f} mean=${keep.pnl.mean():.3f}")
print("\n=== weekly ===")
print(f.groupby("wk").agg(n=("won","size"),wr=("won",lambda x:round(100*x.mean(),1)),tot=("pnl",lambda x:round(x.sum(),1))).to_string())
# cheap-only contribution
cheap=f[f.entry<0.70]; exp=f[f.entry>=0.70]
print(f"\ncheap(<0.70): n={len(cheap)} total=${cheap.pnl.sum():.1f}  | expensive(>=0.70): n={len(exp)} total=${exp.pnl.sum():.1f}")
