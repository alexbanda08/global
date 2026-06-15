"""Validate the pre-subscribe opportunity: per Kalshi 15m market, when does the orderbook
first appear (offset vs slot-start) and how much DEPTH exists at +5/+30/+60/+120s.
Data was collected subscribe-AFTER-open (old way) -> first-quote offset shows the old limit;
depth growth shows whether liquidity exists early (pre-subscribe would capture it)."""
import os, sys
import numpy as np, pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))

ob = pd.read_parquet(os.path.join(ROOT, r"data\v4\canonical\kalshi_orderbook.parquet"))
mk = pd.read_parquet(os.path.join(ROOT, r"data\v4\canonical\kalshi_markets.parquet"))
print("markets cols:", list(mk.columns))
# find open/start time col
tcol = next((c for c in mk.columns if any(k in c.lower() for k in ("open_time", "open_ts", "start", "open"))), None)
print("using market open col:", tcol)
# slot start from ticker: KX..15M-YYMMMDDHHMM... -> use market open time instead (cleaner)
tcol = "open_time_us"
mk2 = mk[["market_ticker", tcol]].dropna().copy()
mk2["open_us"] = pd.to_numeric(mk2[tcol], errors="coerce")  # already microseconds
mk2 = mk2.dropna(subset=["open_us"])
ob = ob.merge(mk2[["market_ticker", "open_us"]], on="market_ticker", how="inner")
ob["off_s"] = (ob["time_us"] - ob["open_us"]) / 1e6
ob = ob[(ob.off_s >= -60) & (ob.off_s <= 900)]
print(f"\norderbook rows joined: {len(ob)}  markets: {ob.market_ticker.nunique()}")

# first-quote offset per market (any quote with a price)
ob["has_quote"] = ob[["yes_ask", "no_ask", "yes_bid", "no_bid"]].notna().any(axis=1)
firstq = ob[ob.has_quote].groupby("market_ticker")["off_s"].min()
print("\n=== first observed quote offset (s after open) — the OLD subscribe-late limit ===")
print(firstq.describe(percentiles=[.1, .25, .5, .75, .9]).round(1).to_string())

# depth (ask sizes) at offset buckets
ob["yes_ask_sz"] = ob.get("yes_ask_size", np.nan)
for lab, lo, hi in [("+0..10s", 0, 10), ("+10..30s", 10, 30), ("+30..60s", 30, 60),
                    ("+60..120s", 60, 120), ("+120..300s", 120, 300)]:
    w = ob[(ob.off_s >= lo) & (ob.off_s < hi)]
    nmk = w.market_ticker.nunique()
    haspx = w[["yes_ask", "no_ask"]].notna().any(axis=1).mean() * 100 if len(w) else 0
    bidsz = w["yes_bid_size"].dropna()
    print(f"  {lab:11s}: rows={len(w):6d} mkts={nmk:4d}  %quote={haspx:4.0f}%  median yes_bid_size={bidsz.median() if len(bidsz) else float('nan')}")
