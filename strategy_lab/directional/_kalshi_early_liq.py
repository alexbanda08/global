import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_kalshi_markets, load_kalshi_orderbook
km = load_kalshi_markets("BTC"); kx = km[(km.series=="KXBTC15M")&(km.status=="finalized")].copy()
ko = load_kalshi_orderbook("BTC").dropna(subset=["yes_bid","yes_ask"]).sort_values("time_us")
opent = dict(zip(kx.market_ticker, kx.open_time_us))
ko = ko[ko.market_ticker.isin(opent)].copy()
ko["off_s"] = ko.apply(lambda r:(r.time_us-opent[r.market_ticker])/1e6, axis=1)
# quote density by offset bucket (how many quotes arrive in each 15s bin after open) + book width/size
bins=[0,15,30,45,60,90,120,300,900]
ko["bk"]=pd.cut(ko.off_s, bins)
ko["spread"]=ko.yes_ask-ko.yes_bid
agg=ko.groupby("bk").agg(n_quotes=("time_us","count"),
                         n_mkts=("market_ticker","nunique"),
                         med_spread=("spread","median"),
                         med_yes_bid_size=("yes_bid_size","median"),
                         med_no_bid_size=("no_bid_size","median"))
print("=== Kalshi KXBTC15M quote arrival & liquidity by seconds-after-open ===")
print(agg.to_string())
# per-market: how many have ANY quote in [0,15],[0,30],[0,60]
firstq = ko.groupby("market_ticker").off_s.min()
for thr in [10,15,30,45,60]:
    print(f"  markets with first quote <= +{thr}s: {(firstq<=thr).sum()}/{len(firstq)} ({100*(firstq<=thr).mean():.0f}%)")
# is the gap collector-poll-latency? check inter-quote gap right after first quote (if ~constant -> poll cadence)
print("\n=== inter-quote spacing in first 120s (poll-cadence tell) ===")
e=ko[ko.off_s<=120].sort_values(["market_ticker","time_us"])
e["dt"]=e.groupby("market_ticker").time_us.diff()/1e6
print("  median inter-quote dt (s):", round(e.dt.median(),2), " p90:", round(e.dt.quantile(.9),2), " max:", round(e.dt.max(),1))
print("  (if first-quote median ~40s AND inter-quote dt ~small -> real illiquid open; if dt~poll-interval -> collector lag)")
