"""
THREAD B-2 — REGIME GATES on the EDGE trend-continuation snipers, using NEW indicators funding_rate + OI
(+ realized vol). Mechanism = established-trend continuation, so it SHOULD be regime-sensitive (unlike the scalp).
Fires = deduped dashboard-metric EDGE sniper fires (recent, where cex_futures exists). Join funding/OI/vol asof
the fire and bucket pnl by tercile / by direction-interaction. DSR-discipline: terciles + bootstrap CI + time
train/test; report nulls honestly. Funding from bybit perp; vol from binance 1s.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_cex_futures_ticker
CANON = ROOT / "data/v4/canonical"

F = pd.read_csv(ROOT/"strategy_lab/directional/_results/edge_sniper_fires_recent.csv",
                names=["sleeve","at_us","dir","won","pnl","ev"])
F = F.dropna(subset=["at_us","pnl"]).copy(); F["at_us"]=F.at_us.astype("int64")
F["coin"]=F.sleeve.str.extract(r"_(btc|eth|sol)_")[0].str.upper()
F["dir"]=F.dir.str.upper().str[:4].replace({"DOWN":"DOWN","UP":"UP"})
print(f"EDGE sniper fires: {len(F)}  coins={F.coin.value_counts().to_dict()}  range="
      f"{pd.to_datetime(F.at_us.min(),unit='us')}..{pd.to_datetime(F.at_us.max(),unit='us')}")

# funding + OI asof (bybit perp), per coin
tk = load_cex_futures_ticker(exchange="bybit")
def asof(ts,v,t):
    i=np.searchsorted(ts,t,"right")-1; return np.where(i>=0, v[np.clip(i,0,len(v)-1)], np.nan)
fund={};oi={};FUT_MAX=int(tk.time_exchange_us.max())
print(f"futures ticker range: {pd.to_datetime(tk.time_exchange_us.min(),unit='us')}..{pd.to_datetime(FUT_MAX,unit='us')}")
for coin in ["BTC","ETH","SOL"]:
    sym=f"BYBIT_PERP_{coin}_USDT"; g=tk[tk.symbol_id==sym].sort_values("time_exchange_us")
    # funding_rate + OI are sparse -> forward-fill so asof returns the last known value
    fr=pd.Series(g.funding_rate.values.astype(float)).ffill().values
    ov=pd.Series(g.open_interest.values.astype(float)).ffill().values
    fund[coin]=(g.time_exchange_us.values.astype("int64"), fr)
    oi[coin]=(g.time_exchange_us.values.astype("int64"), ov)
# fires after the futures window have no funding/OI -> only join those within coverage
F=F[F.at_us<=FUT_MAX].copy()
print(f"fires within futures coverage (<= {pd.to_datetime(FUT_MAX,unit='us')}): {len(F)}")
# vol from binance 1s
vol={}
for coin in ["BTC","ETH","SOL"]:
    df=pd.read_parquet(CANON/"klines_1s.parquet", columns=["symbol_id","time_period_start_us","price_close"],
                       filters=[("symbol_id","==",f"BINANCE_SPOT_{coin}_USDT")]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    vol[coin]=(df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float))

frows=[]
for coin,g in F.groupby("coin"):
    ft,fv=fund[coin]; ot,ov=oi[coin]; vt,vp=vol[coin]; lp=np.log(vp)
    for _,r in g.iterrows():
        t=int(r.at_us)
        fr=float(asof(ft,fv,t)); oinow=float(asof(ot,ov,t)); oi1h=float(asof(ot,ov,t-3600_000_000))
        oichg=(oinow/oi1h-1) if (np.isfinite(oinow) and np.isfinite(oi1h) and oi1h>0) else np.nan
        iv=np.searchsorted(vt,t,"right")-1
        rv=np.std(np.diff(lp[iv-300:iv+1]))*1e4 if iv>=301 else np.nan
        frows.append(dict(sleeve=r.sleeve,coin=coin,dir=r.dir,pnl=r.pnl,at_us=t,funding=fr,oichg=oichg,rv=rv))
D=pd.DataFrame(frows)
print(f"joined fires: {len(D)}  funding non-null={D.funding.notna().sum()}  oichg={D.oichg.notna().sum()}  rv={D.rv.notna().sum()}")

def boot(v,nb=5000):
    v=np.asarray(v)
    if len(v)<5: return (np.nan,np.nan)
    i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def cell(v):
    v=np.asarray(v)
    if len(v)<5: return f"n={len(v):4d} (few)"
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else np.nan; lo,hi=boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] wr={(v>0).mean():.2f}"
def terc(df,feat,lab):
    d=df.dropna(subset=[feat])
    if len(d)<15: print(f"\n--- {lab}: too few ---"); return
    q=d[feat].quantile([1/3,2/3]).values
    d=d.assign(_b=np.where(d[feat]<=q[0],"LOW",np.where(d[feat]<=q[1],"MID","HIGH")))
    print(f"\n--- {lab} ({feat}) terciles ---")
    for b in ["LOW","MID","HIGH"]: print(f"  {b:4s} {cell(d[d._b==b].pnl.values)}")

print(f"\n===== BASELINE (all EDGE snipers pooled) =====\n  {cell(D.pnl.values)}")
for feat,lab in [("funding","funding_rate"),("oichg","OI 1h change"),("rv","realized vol 300s")]:
    terc(D,feat,lab)

# direction interaction: funding sign x direction (trend-continuation hypothesis)
print("\n===== funding SIGN x sleeve direction =====")
for d in ["DOWN","UP"]:
    sub=D[D.dir==d]
    print(f"  dir={d}: fund>0 {cell(sub[sub.funding>0].pnl.values)}")
    print(f"  dir={d}: fund<0 {cell(sub[sub.funding<0].pnl.values)}")

# per-sleeve: best EDGE sleeve under funding regime
print("\n===== per-sleeve x funding sign (BTC ema50_ema800 = strongest EDGE) =====")
for sl in D.sleeve.unique():
    s=D[D.sleeve==sl]
    if len(s)<30: continue
    print(f"  {sl.replace('poly_sniper_v5_','')[:34]:34s} all {cell(s.pnl.values)}")
    print(f"  {'  fund>0':34s}     {cell(s[s.funding>0].pnl.values)}")
    print(f"  {'  fund<0':34s}     {cell(s[s.funding<0].pnl.values)}")

# TRAIN/TEST on the most promising gate
print("\n===== TRAIN/TEST (time split) — candidate gates =====")
D=D.sort_values("at_us"); h=D.at_us.median(); tr=D[D.at_us<=h]; te=D[D.at_us>h]
for name,col,op in [("rv LOW (<train med)","rv","lo"),("funding>0","funding","pos"),("OIchg>0","oichg","pos")]:
    if op=="lo": st=tr[tr[col]<=tr[col].median()]; se=te[te[col]<=tr[col].median()]
    else: st=tr[tr[col]>0]; se=te[te[col]>0]
    print(f"  GATE {name}: TRAIN {cell(st.pnl.values)} | TEST {cell(se.pnl.values)}")
print("\nREAD: real gate lifts $/tr above baseline on BOTH splits w/ CI>0. Funding/OI are NEW indicators; report nulls.")
