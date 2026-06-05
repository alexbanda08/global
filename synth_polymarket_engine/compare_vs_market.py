"""Does a Synth-style zero-drift GBM P(up) beat the MARKET's implied P(up)?
Free, offline, all local data. For each resolved up-down market, at a mid-window
snapshot: model P(up)=Phi(ln(spot/strike)/(sig*sqrt(tau))) vs Polymarket Up-token
mid (market P(up)), scored against the actual outcome.

Tests:
 1. Brier(market) vs Brier(model) vs Brier(calibrated model OOS) vs coinflip.
    -> is the MARKET well-calibrated (efficient)?
 2. Value bet when |model - market| >= tau: WR + $/trade (0.07 fee), entry = token price.
    -> is there exploitable mispricing?

Run: py -3 synth_polymarket_engine/compare_vs_market.py --asset btc --tf 15m --days 6
"""
import sys, argparse, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data" / "v4" / "canonical"))
import numpy as np, pandas as pd
from load import load_resolutions, load_klines, load_orderbook_l25_streaming
from statistics import NormalDist
ND = NormalDist(); PHI = ND.cdf
def phinv(p): return ND.inv_cdf(min(max(p, 1e-6), 1-1e-6))

OFFSET = {"5m": 60, "15m": 120}   # snapshot seconds into window

def realized_sigma_sec(cu, cpx, t_us, lookback_min=60):
    lo = t_us - lookback_min*60*1_000_000
    px = cpx[(cu >= lo) & (cu <= t_us)]
    if len(px) < 10: return None
    s1m = np.std(np.diff(np.log(px)))
    return s1m/math.sqrt(60.0) if s1m > 0 else None

def up_mid_asof(book_up, t_us):
    ts, ask_px, ask_sz, bid_px, bid_sz = book_up
    i = np.searchsorted(ts, t_us, side="right") - 1
    if i < 0: return None
    ba, bb = ask_px[i, 0], bid_px[i, 0]
    if not (0 < bb <= ba < 1): return None
    return (ba + bb) / 2.0

def pnl_07(won, vwap): return (1-vwap)*(1-0.07*vwap) if won else -vwap

def brier(p, y): return float(np.mean((np.asarray(p)-np.asarray(y))**2))

def calibrate_oos(model_p, y):
    """quantile-bin calibrator trained on first half, applied to second half."""
    n=len(model_p); h=n//2
    Ptr,Ytr=np.array(model_p[:h]),np.array(y[:h]); Pte,Yte=np.array(model_p[h:]),np.array(y[h:])
    o=np.argsort(Ptr); Ps,Ys=Ptr[o],Ytr[o]
    bins=np.array_split(np.arange(len(Ps)),20); edges=[Ps[b[-1]] for b in bins]; rates=[Ys[b].mean() for b in bins]
    def cal(p):
        for e,r in zip(edges,rates):
            if p<=e: return r
        return rates[-1]
    Pc=np.array([cal(p) for p in Pte])
    return brier(Pc,Yte), brier(Pte,Yte), Yte

def run(asset, tf, days, lookback):
    res = load_resolutions()
    res = res[res["slug"].astype(str).str.contains(f"{asset}-updown-{tf}-")].dropna(
        subset=["strike_price","outcome","slot_start_us","slot_end_us"]).sort_values("slot_start_us")
    max_us = int(res["slot_end_us"].max()); min_us = max_us - days*86400*1_000_000
    res = res[res["slot_start_us"] >= min_us]
    slugs = set(res["slug"])
    print(f"[{asset} {tf}] markets in last {days}d: {len(res)}  (loading L25...)")
    books = load_orderbook_l25_streaming(asset, slugs=slugs, subsample_1hz=True,
                                         min_ts_us=min_us-120_000_000, max_ts_us=max_us+5_000_000)
    kl = load_klines(asset); kl = kl[kl["period_id"]=="1MIN"]
    cu = kl["time_period_end_us"].to_numpy(); cpx = kl["price_close"].to_numpy()
    o=np.argsort(cu); cu,cpx=cu[o],cpx[o]
    off = OFFSET[tf]*1_000_000
    rows=[]
    for _,m in res.iterrows():
        slug=m["slug"]; key=(slug,"Up")
        if key not in books: continue
        t=int(m["slot_start_us"])+off
        if t>=int(m["slot_end_us"]): continue
        mkt=up_mid_asof(books[key], t)
        if mkt is None: continue
        i=np.searchsorted(cu,t,side="right")-1
        if i<0: continue
        spot=cpx[i]; strike=float(m["strike_price"]); tau=(int(m["slot_end_us"])-t)/1e6
        sig=realized_sigma_sec(cu,cpx,t,lookback)
        if not sig or tau<=0: continue
        model=PHI(math.log(spot/strike)/(sig*math.sqrt(tau)))
        y=1 if str(m["outcome"]).lower()=="up" else 0
        rows.append({"model":model,"market":mkt,"y":y,"spot":spot,"strike":strike,"tau":tau,"sig":sig})
    d=pd.DataFrame(rows)
    if len(d)<50: print(f"  too few joined ({len(d)})"); return
    print(f"  joined snapshots: {len(d)} | base P(up)={d.y.mean():.3f}")
    bm=brier(d.market,d.y); bmod=brier(d.model,d.y); coin=brier([0.5]*len(d),d.y)
    bcal,braw_te,_=calibrate_oos(d.model.tolist(),d.y.tolist())
    print(f"  BRIER: market={bm:.4f}  model={bmod:.4f}  model_calibrated_OOS={bcal:.4f}  coin={coin:.4f}")
    print(f"  -> market {'BEATS' if bm<min(bmod,bcal) else 'does NOT beat'} model (lower=better) | "
          f"market {'better' if bm<coin else 'NOT better'} than coin")
    # mispricing / value bet
    print(f"  VALUE BET (bet side of model-vs-market gap, fee 0.07, entry=token price):")
    print(f"    {'tau':>5} {'n':>5} {'WR':>6} {'$/trade':>8} {'total$':>9}")
    for tau in (0.03,0.05,0.08):
        b=[]
        for _,r in d.iterrows():
            e=r.model-r.market
            if abs(e)<tau: continue
            up=e>0; vwap=r.market if up else (1-r.market)
            won=(r.y==1) if up else (r.y==0)
            b.append(pnl_07(won,min(max(vwap,0.02),0.98)))
        if b: print(f"    {tau:>5} {len(b):>5} {sum(1 for x in b if x>0)/len(b)*100:>5.1f}% {np.mean(b):>8.3f} {sum(b):>9.2f}")
        else: print(f"    {tau:>5} {0:>5}  (no bets)")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--asset",default="btc"); ap.add_argument("--tf",default="15m")
    ap.add_argument("--days",type=int,default=6); ap.add_argument("--lookback",type=int,default=60)
    a=ap.parse_args(); run(a.asset,a.tf,a.days,a.lookback)

if __name__=="__main__": main()
