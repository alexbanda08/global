import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_kalshi_markets, load_kalshi_orderbook
km = load_kalshi_markets("BTC")
print("MARKET COLS:", list(km.columns))
kx = km[km.series == "KXBTC15M"].copy() if "series" in km.columns else km
print("KXBTC15M rows:", len(kx), " statuses:", kx.status.value_counts().to_dict() if "status" in kx.columns else "n/a")
print(kx.head(3).to_string())
ko = load_kalshi_orderbook("BTC")
print("\nORDERBOOK COLS:", list(ko.columns))
print("ob rows:", len(ko))
# timing: earliest quote vs open_time and vs (close_time-900s) per market
kf = kx[kx.status == "finalized"].copy() if "status" in kx.columns else kx
ko2 = ko.dropna(subset=["yes_bid","yes_ask"]) if {"yes_bid","yes_ask"}.issubset(ko.columns) else ko
g = ko2.groupby("market_ticker").time_us.agg(["min","max","count"])
kf = kf.merge(g, left_on="market_ticker", right_index=True, how="left")
tcols = [c for c in ["open_time_us","close_time_us","expiration_time_us","strike_time_us"] if c in kf.columns]
print("\ntime cols present:", tcols)
kf = kf.dropna(subset=["min"])
for tc in tcols:
    kf[f"firstq_after_{tc}_s"] = (kf["min"] - kf[tc]) / 1e6
print(f"\nfinalized KXBTC15M with quotes: {len(kf)}")
for tc in tcols:
    s = kf[f"firstq_after_{tc}_s"].describe(percentiles=[.1,.25,.5,.75,.9])
    print(f"  first quote minus {tc} (sec): median={s['50%']:.0f}  p10={s['10%']:.0f} p90={s['90%']:.0f} min={s['min']:.0f} max={s['max']:.0f}")
# window length sanity
if {"open_time_us","close_time_us"}.issubset(kf.columns):
    print("  window len (close-open) sec median:", ((kf.close_time_us-kf.open_time_us)/1e6).median())
print("\nsample rows (ticker, open, close, firstquote):")
show=["market_ticker"]+tcols+["min","count"]
print(kf[show].head(5).to_string())
