"""PHASE 0 — gate the whole project. Does Synth's P(up) beat the market's P(up)?

Steps:
 1. Pull historical synth-vs-poly snapshots (needs SYNTH_API_KEY; caches to _synth_hist.parquet).
 2. Join to canonical resolutions (actual UP/DOWN) by slug.
 3. CALIBRATION: Brier score + reliability for synth_probability_up vs polymarket_probability_up.
    -> Synth must beat the market's Brier to have ANY edge. This is make-or-break.
 4. VALUE-BET backtest: bet when |synth_p - poly_p| >= tau, fee via 0.07 winner-only curve.
    (Swap entry price for engine_v2 L25 fill for full realism — TODO marked.)

Run:  set SYNTH_API_KEY, then  py -3 synth_polymarket_engine/validate_synth_edge.py --pull --asset BTC --tf 15min
      (or --no-pull to reuse cache)
"""
from __future__ import annotations
import sys, os, argparse, datetime
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "data" / "v4" / "canonical"))
import pandas as pd, numpy as np
import synth_client as sc

CACHE = HERE / "_synth_hist.parquet"

# ---------- 1. historical pull ----------
def pull_history(asset, tf, start, end, step_min):
    """Iterate start_time across [start,end] at step_min cadence, snapshot synth-vs-poly.
    CREDIT-HEAVY. Caches result."""
    rows = []
    t = start
    while t < end:
        snap = sc.polymarket_up_down(asset, tf, start_time=t.strftime("%Y-%m-%dT%H:%M:%SZ"))
        if isinstance(snap, dict) and "synth_probability_up" in snap:
            rows.append({"asset": asset, "tf": tf,
                         "slug": snap.get("slug"),
                         "synth_p": float(snap["synth_probability_up"]),
                         "poly_p": float(snap.get("polymarket_probability_up")) if snap.get("polymarket_probability_up") is not None else np.nan,
                         "start_price": snap.get("start_price"),
                         "event_end": snap.get("event_end_time"),
                         "snap_time": t.isoformat()})
        t += datetime.timedelta(minutes=step_min)
    df = pd.DataFrame(rows)
    if CACHE.exists():
        df = pd.concat([pd.read_parquet(CACHE), df], ignore_index=True).drop_duplicates(["slug","snap_time"])
    df.to_parquet(CACHE)
    return df

# ---------- 2. join canonical outcomes ----------
def join_outcomes(df):
    from load import load_resolutions
    res = load_resolutions()[["slug", "outcome"]].copy()   # outcome: 'Up'/'Down' (chainlink)
    res["won_up"] = (res["outcome"].astype(str).str.lower() == "up").astype(int)
    m = df.merge(res, on="slug", how="inner")
    return m.dropna(subset=["synth_p", "poly_p", "won_up"])

# ---------- 3. calibration ----------
def brier(p, y): return float(np.mean((np.asarray(p) - np.asarray(y))**2))
def reliability(p, y, bins=10):
    p=np.asarray(p); y=np.asarray(y); out=[]
    for lo in np.linspace(0,1,bins,endpoint=False):
        hi=lo+1/bins; m=(p>=lo)&(p<hi)
        if m.sum(): out.append((round((lo+hi)/2,2), int(m.sum()), round(p[m].mean(),3), round(y[m].mean(),3)))
    return out

def report_calibration(m):
    bs_s, bs_p = brier(m["synth_p"], m["won_up"]), brier(m["poly_p"], m["won_up"])
    print(f"\n=== CALIBRATION (n={len(m)}) ===")
    print(f"Brier  synth={bs_s:.4f}   market={bs_p:.4f}   -> {'SYNTH BETTER' if bs_s<bs_p else 'market better/equal'} (lower=better)")
    print(f"Base rate P(up)={m['won_up'].mean():.3f}  | synth mean p={m['synth_p'].mean():.3f}  market mean p={m['poly_p'].mean():.3f}")
    print("reliability (bin_mid, n, mean_p, realized) — synth then market:")
    print("  synth :", reliability(m["synth_p"], m["won_up"]))
    print("  market:", reliability(m["poly_p"], m["won_up"]))
    return bs_s, bs_p

# ---------- 4. value-bet backtest ----------
def pnl_07(won, vwap):  # winner-only 0.07 curve (CLAUDE.md canonical)
    return (1-vwap)*(1-0.07*vwap) if won else -vwap

def backtest(m, taus=(0.03,0.05,0.08,0.10)):
    print("\n=== VALUE-BET BACKTEST (entry = de-vigged market prob; TODO: swap engine_v2 L25 fill) ===")
    print(f"{'tau':>5} {'n':>5} {'WR':>6} {'$/trade':>8} {'total$':>9}")
    for tau in taus:
        bets=[]
        for _,r in m.iterrows():
            e=r["synth_p"]-r["poly_p"]
            if abs(e)<tau: continue
            side_up = e>0
            # entry price you pay = market prob of the side you buy
            vwap = r["poly_p"] if side_up else (1-r["poly_p"])
            won = (r["won_up"]==1) if side_up else (r["won_up"]==0)
            bets.append(pnl_07(won, max(min(vwap,0.99),0.01)))
        if bets:
            import statistics as st
            print(f"{tau:>5} {len(bets):>5} {sum(1 for b in bets if b>0)/len(bets)*100:>5.1f}% {st.mean(bets):>8.3f} {sum(bets):>9.2f}")
        else:
            print(f"{tau:>5} {0:>5}  (no bets)")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pull",action="store_true"); ap.add_argument("--no-pull",dest="pull",action="store_false")
    ap.add_argument("--asset",default="BTC"); ap.add_argument("--tf",default="15min")
    ap.add_argument("--days",type=int,default=30); ap.add_argument("--step-min",type=int,default=15)
    ap.set_defaults(pull=True)
    a=ap.parse_args()
    if a.pull:
        end=datetime.datetime.utcnow(); start=end-datetime.timedelta(days=a.days)
        print(f"pulling {a.asset} {a.tf} {start:%Y-%m-%d}..{end:%Y-%m-%d} every {a.step_min}min (credits!)")
        df=pull_history(a.asset,a.tf,start,end,a.step_min)
    else:
        df=pd.read_parquet(CACHE)
    df=df[(df.asset==a.asset)&(df.tf==a.tf)]
    print(f"snapshots: {len(df)}")
    m=join_outcomes(df)
    print(f"joined to canonical outcomes: {len(m)}")
    if len(m)<30:
        print("too few joined rows — widen window or check slug match"); return
    report_calibration(m)
    backtest(m)

if __name__=="__main__":
    main()
