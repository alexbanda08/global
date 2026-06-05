"""FREE premise test (no Synth key). Question: can a realized-vol GBM model produce
a CALIBRATED, better-than-coinflip P(up) at a mid-window snapshot for Polymarket
up-down markets? This is the mechanism Synth's edge rests on.

Model P(up) at snapshot t (offset seconds into the window):
    spot_t = binance close as-of t ; strike = resolution strike_price ; tau = (slot_end - t) sec
    sigma_sec = std(1m log returns over trailing LOOKBACK) / sqrt(60)
    P(up) = Phi( ln(spot_t/strike) / (sigma_sec * sqrt(tau)) )      (GBM, ~0 drift)
Outcome = 1 if resolution outcome == 'Up'.
Reports Brier + reliability + WR(argmax) + AUC vs coinflip(0.25). NOTE: this tests the
MODEL's calibration vs OUTCOMES, not yet vs the MARKET price (that needs L25 or a Synth key).

Run: py -3 synth_polymarket_engine/baseline_calibration.py --asset btc --tf 15m --offset 120
"""
import sys, argparse, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data" / "v4" / "canonical"))
import numpy as np, pandas as pd
from load import load_resolutions, load_klines, asof_strict
from statistics import NormalDist
PHI = NormalDist().cdf

def realized_sigma_sec(closes_us, closes_px, t_us, lookback_min=60):
    # 1m log-returns over trailing lookback ending at t
    lo = t_us - lookback_min*60*1_000_000
    mask = (closes_us>=lo)&(closes_us<=t_us)
    px = closes_px[mask]
    if len(px) < 10: return None
    r = np.diff(np.log(px))
    s1m = np.std(r)
    return s1m/math.sqrt(60.0) if s1m>0 else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--asset",default="btc"); ap.add_argument("--tf",default="15m")
    ap.add_argument("--offset",type=int,default=120,help="seconds into window for snapshot")
    ap.add_argument("--lookback",type=int,default=60,help="vol lookback minutes")
    ap.add_argument("--limit",type=int,default=4000)
    a=ap.parse_args()

    res=load_resolutions()
    res=res[res["slug"].astype(str).str.contains(f"{a.asset}-updown-{a.tf}-")].copy()
    res=res.dropna(subset=["strike_price","outcome","slot_start_us","slot_end_us"])
    res=res.sort_values("slot_start_us").tail(a.limit)
    print(f"{a.asset} {a.tf} resolved markets: {len(res)}")

    kl=load_klines(a.asset)            # binance signal source
    if "period_id" in kl: kl=kl[kl["period_id"]=="1MIN"]
    cu=kl["time_period_end_us"].to_numpy()
    cpx=kl["price_close"].to_numpy()
    order=np.argsort(cu); cu=cu[order]; cpx=cpx[order]

    rows=[]
    for _,m in res.iterrows():
        t=int(m["slot_start_us"])+a.offset*1_000_000
        if t>=int(m["slot_end_us"]): t=int(m["slot_end_us"])-1
        spot=asof_strict(int(m["slot_end_us"]), {"us":cu,"px":cpx} if False else None, t) if False else None
        # simple as-of: last close <= t
        idx=np.searchsorted(cu,t,side="right")-1
        if idx<0: continue
        spot=cpx[idx]
        strike=float(m["strike_price"])
        tau=(int(m["slot_end_us"])-t)/1_000_000
        if tau<=0: continue
        sig=realized_sigma_sec(cu,cpx,t,a.lookback)
        if not sig: continue
        z=math.log(spot/strike)/(sig*math.sqrt(tau))
        p_up=PHI(z)
        y=1 if str(m["outcome"]).lower()=="up" else 0
        rows.append((p_up,y,spot,strike))
    df=pd.DataFrame(rows,columns=["p_up","y","spot","strike"])
    print(f"scored: {len(df)} | base rate P(up)={df['y'].mean():.3f}")
    if len(df)<50: print("too few"); return

    brier=float(np.mean((df["p_up"]-df["y"])**2))
    coin=float(np.mean((0.5-df["y"])**2))
    # WR betting argmax side
    df["bet_up"]=df["p_up"]>0.5
    df["correct"]=df["bet_up"]==(df["y"]==1)
    wr=df["correct"].mean()
    # AUC
    from bisect import bisect
    pos=df[df.y==1]["p_up"].to_numpy(); neg=df[df.y==0]["p_up"].to_numpy()
    auc=np.mean([(pos[:,None]>neg[None,:]).mean()]) if len(pos)*len(neg) else float('nan')
    print(f"\n=== MODEL CALIBRATION (snapshot +{a.offset}s, vol lookback {a.lookback}m) ===")
    print(f"Brier(model)={brier:.4f}   Brier(coinflip 0.5)={coin:.4f}   -> {'INFORMATIVE' if brier<coin-0.005 else 'no better than coin'}")
    print(f"WR(bet model argmax)={wr*100:.1f}%   AUC={auc:.3f}")
    # reliability
    print("reliability (bin_mid, n, mean_p, realized):")
    for lo in np.linspace(0,1,10,endpoint=False):
        hi=lo+0.1; mk=(df.p_up>=lo)&(df.p_up<hi)
        if mk.sum(): print(f"  {(lo+hi)/2:.2f}  n={int(mk.sum()):4d}  p={df.p_up[mk].mean():.3f}  real={df.y[mk].mean():.3f}")
    print("\nNOTE: this is MODEL-vs-OUTCOME calibration. To test the EDGE we must compare to the")
    print("MARKET-implied P(up) at the same snapshot (needs L25 book or a Synth API key).")

if __name__=="__main__":
    main()
