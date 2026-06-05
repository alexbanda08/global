"""
20 — Pass 1: per-sleeve resolution stats for ALL sleeves (shadow + sniper + momo).
Filter: active in window, n>=30, WR>55%, positive total. Flag leverage-only (per-$ <=0).
Writes per-fire records (sleeve, asset, tf, slug, dir, won, pnl, pnl_per_$, fire_us) for Pass-2 correlation.
"""
import pandas as pd, numpy as np, json, os, datetime as dt
ROOT=r"C:\Users\alexandre bandarra\Desktop\global"
EV=os.path.join(ROOT,r"data\v4\canonical\trading_events_30d.parquet")
OUTD=os.path.join(ROOT,r"strategy_lab\_opt_2026_05_30\_results")
df=pd.read_parquet(EV, columns=["at","sleeve_id","kind","data"])
print("events max at:", df["at"].max(), " total:", len(df))
res=df[df["kind"]=="poly_updown_resolution"].copy()
# window: last 21 days from max
cut=pd.Timestamp(df["at"].max())-pd.Timedelta(days=21)
res=res[pd.to_datetime(res["at"])>=cut]
def J(d):
    if isinstance(d,dict): return d
    try: return json.loads(d)
    except: return {}
def f(x):
    try: return float(x)
    except: return np.nan
recs=[]
for at,sid,data in zip(res["at"],res["sleeve_id"],res["data"]):
    d=J(data)
    direction=d.get("direction") or d.get("signal")
    entry=d.get("fill_vwap"); entry=d.get("entry_price") if entry is None else entry
    placed=d.get("placed_size_usd")
    if placed is None:
        eq=f(d.get("entry_qty")); ep=f(d.get("entry_price")); placed=eq*ep if (eq==eq and ep==ep) else np.nan
    pnl=f(d.get("pnl_usd"))
    recs.append(dict(at=at, sleeve=sid, asset=(d.get("asset") or d.get("symbol") or "").upper(),
        tf=d.get("tf"), slug=d.get("slug"), direction=direction, won=bool(d.get("won")),
        pnl=pnl, placed=f(placed), fire_us=d.get("fire_us"),
        ppd=(pnl/f(placed)) if (f(placed) and f(placed)==f(placed) and f(placed)!=0) else np.nan))
R=pd.DataFrame(recs)
R.to_parquet(os.path.join(OUTD,"all_sleeve_fires.parquet"),index=False)
g=R.groupby("sleeve").agg(
    asset=("asset", lambda x: x.mode().iat[0] if len(x.mode()) else ""),
    tf=("tf", lambda x: x.mode().iat[0] if len(x.mode()) else ""),
    n=("won","size"), wr=("won",lambda x:round(100*x.mean(),1)),
    dpt=("pnl",lambda x:round(x.mean(),3)), total=("pnl",lambda x:round(x.sum(),1)),
    ppd=("ppd",lambda x:round(np.nanmean(x),4))).reset_index()
g["lev_only"]=g["ppd"]<=0
qual=g[(g.n>=30)&(g.wr>55.0)&(g.total>0)].sort_values("total",ascending=False)
qual.to_csv(os.path.join(OUTD,"qualifying_sleeves.csv"),index=False)
pd.set_option("display.width",240); pd.set_option("display.max_rows",120)
print(f"\n=== ALL sleeves with n>=30 in last 21d: {len(g)} ; QUALIFYING (WR>55, total>0): {len(qual)} ===")
print(qual[["sleeve","asset","tf","n","wr","dpt","total","ppd","lev_only"]].to_string(index=False))
print("\nby market (asset x tf) count of qualifying:")
print(qual.groupby(["asset","tf"]).size().to_string())
