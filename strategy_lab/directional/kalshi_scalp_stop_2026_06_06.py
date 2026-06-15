"""
KALSHI scalp STOP-LOSS test — does a stop @ entry-0.10 help on kalshi_scalp_exit_btc_15m_d3_v1?
Mirrors the Poly per-TF stop analysis. Live: KXBTC15M, fire @ ws+60s, buy LEADING side at Kalshi ask,
entry_band (0,0.55), delta>=3, exit +60s (ws+120). Stop = leading BID crosses ev-0.10 in (fire,deadline]
-> taker-cross at that level (with slippage variants); else taker at bid_dead. Compare to pure taker +60.
Kalshi fee = ceil(0.07*P*(1-P)) cents, TAKER. Short sample (Jun2-5). bootstrap CI.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_kalshi_markets, load_kalshi_orderbook
CANON = ROOT / "data/v4/canonical"

km = load_kalshi_markets("BTC"); km = km[(km.series == "KXBTC15M") & (km.status == "finalized")].copy()
ko = load_kalshi_orderbook("BTC").dropna(subset=["yes_bid","yes_ask","no_bid","no_ask"]).sort_values("time_us")
b = pd.read_parquet(CANON/"klines_1s.parquet", columns=["symbol_id","time_period_start_us","price_close"],
                    filters=[("symbol_id","==","BINANCE_SPOT_BTC_USDT")]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
be, bc = b.time_period_start_us.values.astype("int64"), b.price_close.values.astype(float)
def asof(ts,v,t):
    i=np.searchsorted(ts,t,"right")-1; return np.where(i>=0, v[np.clip(i,0,len(v)-1)], np.nan)
kfee = lambda p: np.ceil(0.07*p*(1-p)*100)/100
kidx = {mt:g for mt,g in ko.groupby("market_ticker")}

recs=[]
for _,m in km.iterrows():
    ws=int(m.open_time_us); fire=ws+60_000_000; deadline=fire+60_000_000
    ret=float(asof(be,bc,fire)/asof(be,bc,fire-5_000_000)-1.0)
    if not np.isfinite(ret): continue
    db=abs(ret)*1e4
    if db<3.0: continue
    lead_up=ret>0
    kq=kidx.get(m.market_ticker)
    if kq is None: continue
    t=kq.time_us.values
    bid=kq.yes_bid.values if lead_up else kq.no_bid.values
    ask=kq.yes_ask.values if lead_up else kq.no_ask.values
    je=np.searchsorted(t,fire,"right")-1
    if je<0: continue
    ev=float(ask[je])
    if not np.isfinite(ev) or ev<=0 or ev>=0.55: continue
    won=(m.result=="yes")==lead_up
    win=(t>fire)&(t<=deadline); tw,bidw=t[win],bid[win]
    jd=np.searchsorted(t,deadline,"right")-1
    bid_dead=float(bid[jd]) if jd>=0 and np.isfinite(bid[jd]) else (1.0 if won else 0.0)
    taker=(bid_dead-ev)-kfee(bid_dead)
    rec=dict(mt=m.market_ticker, ev=ev, won=won, bid_dead=bid_dead, taker=taker, db=db,
             spread=float(ask[je]-bid[je]))
    stop_lvl=ev-0.10
    bidw_valid=bidw[np.isfinite(bidw)]
    hit=len(bidw_valid)>0 and float(np.min(bidw_valid))<=stop_lvl
    for slip in [0.0,0.03,0.06]:
        if hit:
            sell=max(stop_lvl-slip,0.01); rec[f"stop_s{int(slip*100)}"]=(sell-ev)-kfee(sell)
        else:
            rec[f"stop_s{int(slip*100)}"]=taker
    rec["hit_stop"]=hit
    recs.append(rec)
D=pd.DataFrame(recs)
print(f"gated Kalshi scalp fires (delta>=3, entry<0.55): {len(D)}  mean entry={D.ev.mean():.3f} "
      f"mean spread={D.spread.mean():.3f} won={D.won.mean():.3f}")
def boot(v,nb=5000):
    v=np.asarray(v)
    if len(v)<5 or v.std()==0: return (v.mean(),v.mean())
    i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def show(col,lab):
    v=D[col].dropna().values
    if len(v)<5: print(f"  {lab:28s} n={len(v)} (few)"); return
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else float("nan"); lo,hi=boot(v)
    print(f"  {lab:28s} n={len(v):3d} $/contract={v.mean():+.4f} t={t:+.2f} CI=[{lo:+.4f},{hi:+.4f}]")
print("\n=== KALSHI scalp: STOP@entry-0.10 vs pure taker +60 (per 1 contract = $1) ===")
show("taker","(1) pure taker +60")
for s in [0,3,6]: show(f"stop_s{s}", f"(1b) taker+60 +STOP slip{s}c")
print("\n=== paired: stop - taker ===")
for s in [0,3,6]:
    d=(D[f"stop_s{s}"]-D["taker"]).dropna().values; lo,hi=boot(d)
    sig="SIG+" if lo>0 else ("SIG-" if hi<0 else "ns")
    print(f"  stop_s{s}c - taker: mean={d.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}] {sig}")
print(f"\nstop triggered on {int(D.hit_stop.sum())}/{len(D)} ({100*D.hit_stop.mean():.1f}%)")
print("CAVEAT: bid-path proxy (no Kalshi trade tape), ignores slippage beyond tested cents; short sample Jun2-5;")
print("entry lag = binance 5s proxy. Stop fill optimistic (sells at level).")
