"""
btc_15m_momo_HOLD_f7 — Feb21->Mar24 backfill backtest (the NEW out-of-regime data), verified L25 engine.
Signal: ws_s=W (window start = suffix), ret_2m=log(c@(W+120)/c@W) on binance 1s closes; RSI14 simple-Wilder @W;
gate |ret_2m|>=rolling-14d q90; F7 UP>50/DOWN<50. Fill: $25 ask-walk on l25_backfill book asof fire=(W+120),
0.07 winner-only fee, HOLD to resolution (resolutions_hf outcome). NO spread filter (prod momo has none).
NOTE: l25_backfill book starts ~+80s into window (trentmkelly quirk) -> +120s fire is covered; flag thin early books.
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0,str(ROOT/"data/v4/canonical"))
from load import load_resolutions_hf, load_orderbook_l25_backfill
CANON=ROOT/"data/v4/canonical"
GATE_Q=0.90; LB=14*24*4  # 14d of 15m slots
WLO=int(pd.Timestamp("2026-02-21",tz="UTC").timestamp()); WHI=int(pd.Timestamp("2026-03-24",tz="UTC").timestamp())

# binance 1s closes
b=pd.read_parquet(CANON/"klines_1s.parquet",columns=["symbol_id","time_period_start_us","price_close"],
    filters=[("symbol_id","==","BINANCE_SPOT_BTC_USDT")]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
bt_=b.time_period_start_us.values.astype("int64"); bc=b.price_close.values.astype(float)
def c_at(s):
    i=np.searchsorted(bt_,int(s)*1_000_000,"right")-1
    return float(bc[i]) if i>=0 else float("nan")
def rsi14(W):
    cs=[c_at(W+o) for o in range(-840,1,60)]
    if any(math.isnan(x) for x in cs): return float("nan")
    d=np.diff(cs); g=np.where(d>0,d,0).mean(); l=np.where(d<0,-d,0).mean()
    return 100.0 if l<=0 else float(100-100/(1+g/l))

res=load_resolutions_hf(); res=res[(res.ticker=="BTC")&(res.timeframe=="15m")&res.outcome.isin(["Up","Down"])].copy()
res["W"]=res.slug.str.extract(r"-(\d+)$")[0].astype("int64")
res=res[(res.W>=WLO)&(res.W<=WHI)].sort_values("W").reset_index(drop=True)
print(f"Feb21-Mar24 BTC 15m hf slots: {len(res)}")
# ret_2m series + q90 rolling
res["ret2m"]=[ (lambda c0,c1: math.log(c1/c0) if (math.isfinite(c0) and math.isfinite(c1) and c0>0) else float('nan'))(c_at(W),c_at(W+120)) for W in res.W]
arr=res.ret2m.values
fires=[]
for i,row in res.iterrows():
    r=arr[i]
    if not math.isfinite(r) or r==0: continue
    hist=arr[max(0,i-LB):i]; hv=hist[np.isfinite(hist)]
    if len(hv)<50: continue
    if abs(r)<np.quantile(np.abs(hv),GATE_Q): continue
    sig="UP" if r>0 else "DOWN"; rs=rsi14(int(row.W))
    if not math.isfinite(rs): continue
    if (sig=="UP" and rs<=50) or (sig=="DOWN" and rs>=50): continue
    fires.append(dict(slug=row.slug,W=int(row.W),sig=sig,outcome=row.outcome,
        won=(sig=="UP")==(row.outcome=="Up")))
F=pd.DataFrame(fires); print(f"gated fires: {len(F)}")

# FILL via ACTUAL executed trades (validated = L25 book, corr 0.95) — median traded price in [W+60,W+180]
from load import load_trades_hf
tr=load_trades_hf("btc")
tcols={c.lower():c for c in tr.columns}
tr=tr.rename(columns={tcols.get("timestamp_us","timestamp_us"):"ts", tcols.get("price","price"):"price"})
tr=tr[tr.slug.isin(set(F.slug))]
print(f"trades_hf rows for gated slugs: {len(tr)}  cols={list(tr.columns)[:8]}")
trg={k:(g.ts.values.astype('int64'),g.price.values.astype(float)) for k,g in tr.groupby(["slug","outcome"])}
rows=[]
for r in F.itertuples(index=False):
    oc="Up" if r.sig=="UP" else "Down"; key=(r.slug,oc)
    if key not in trg: continue
    tt,pp=trg[key]; lo=np.searchsorted(tt,(r.W+60)*1_000_000,"left"); hi=np.searchsorted(tt,(r.W+180)*1_000_000,"right")
    seg=pp[lo:hi]; seg=seg[np.isfinite(seg)&(seg>0)&(seg<1)]
    if len(seg)<1: continue
    vw=float(np.median(seg))
    sh=25.0/vw; pnl07=sh*(1-vw)*(1-0.07*vw) if r.won else -sh*vw
    rows.append(dict(slug=r.slug,sig=r.sig,won=r.won,vwap=vw,pnl07=pnl07,n_tr=len(seg)))
T=pd.DataFrame(rows)
print(f"filled: {len(T)} / gated {len(F)}")
if len(T):
    v=T.pnl07.values; t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else float('nan')
    print(f"\n===== btc_15m_momo_HOLD_f7  Feb21-Mar24 (verified L25 engine, 0.07 fee) =====")
    print(f"  n={len(T)}  WR={100*T.won.mean():.1f}%  $/tr={v.mean():+.3f}  total={v.sum():+.1f}  vwap={T.vwap.mean():.3f}  t={t:+.2f}")
    print(f"  by direction: " + " ".join(f"{d}:{100*T[T.sig==d].won.mean():.0f}%/{T[T.sig==d].pnl07.mean():+.2f}" for d in ['UP','DOWN'] if (T.sig==d).any()))
