import pandas as pd, numpy as np, os, json
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"; RES=os.path.join(ROOT,r"data\v4\canonical\_results")
# full period reconstruction
df=pd.read_parquet(os.path.join(RES,"sniper_btc15m_v8_gated.parquet"))
m=(df.direction=="DOWN")&df["g_tr_above_ema50"].fillna(False)&df["g_tr_above_ema800"].fillna(False)&(df.fire_offset_s==600)
f=df[m].copy(); f["entry"]=f.entry_vwap.astype(float)
sh=5.0/f.entry.clip(1e-3); f["pnl"]=np.where(f.won.astype(bool), sh*(1-f.entry)*(1-0.07*f.entry), -sh*f.entry)
print("=== FULL-PERIOD ENTRY-BAND sweep [lo,hi] (n=917 base, total +$176) ===")
for lo,hi in [(0.0,1.01),(0.15,1.01),(0.15,0.95),(0.15,0.90),(0.20,0.95),(0.15,0.92),(0.30,0.95),(0.15,0.97)]:
    s=f[(f.entry>=lo)&(f.entry<hi)]
    print(f"  [{lo:.2f},{hi:.2f}): n={len(s):4d} WR={100*s.won.mean():.1f}% total=${s.pnl.sum():7.1f} mean=${s.pnl.mean():.3f}")
print("\n  >=0.95 bucket alone:")
hi=f[f.entry>=0.95]; print(f"   n={len(hi)} WR={100*hi.won.mean():.1f}% total=${hi.pnl.sum():.1f} mean=${hi.pnl.mean():.3f} (each win ~+${5/0.98*0.02:.2f}, each loss -$5)")

# last live fires
EV=os.path.join(ROOT,r"data\v4\canonical\trading_events_30d.parquet")
e=pd.read_parquet(EV, columns=["at","sleeve_id","kind","data"])
e=e[(e.sleeve_id=="poly_sniper_v5_btc_15m_ema50_ema800_off600_down")&(e.kind=="poly_updown_resolution")].copy()
def J(d):
    if isinstance(d,dict): return d
    try: return json.loads(d)
    except: return {}
rows=[]
for at,d in zip(e["at"],e["data"]):
    d=J(d); rows.append(dict(at=pd.Timestamp(at), entry=d.get("fill_vwap"), won=d.get("won"), pnl=d.get("pnl_usd"), slug=d.get("slug")))
L=pd.DataFrame(rows).sort_values("at")
print("\n=== LAST 12 LIVE fires (base sleeve) ===")
print(L.tail(12).to_string(index=False))
# live >=0.95 bucket
L["entry"]=pd.to_numeric(L.entry,errors="coerce"); L["pnl"]=pd.to_numeric(L.pnl,errors="coerce")
hl=L[L.entry>=0.95]
print(f"\nLIVE >=0.95 bucket: n={len(hl)} WR={100*hl.won.mean():.1f}% total=${hl.pnl.sum():.1f} mean=${hl.pnl.mean():.3f}")
