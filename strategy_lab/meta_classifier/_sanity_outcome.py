"""Sanity-check: does outcome='Up' correlate with asset rising from ws to ws+window?

If outcome encoding is sane:
  for outcome='Up' on a btc-updown-Xm market, BTC@(ws+window) should be > BTC@ws
  (where window=300s for 5m, 900s for 15m)

Tests several anchor candidates to figure out which ws-encoding actually matches.
"""
import math
import numpy as np
import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
REFRESH = rf"{ROOT}\data\v4\refresh_2026_05_06"

ASSET_BIN = {"BTC":"BINANCE_SPOT_BTC_USDT","ETH":"BINANCE_SPOT_ETH_USDT","SOL":"BINANCE_SPOT_SOL_USDT"}

# Load 1m klines, build asof
print("loading klines…")
k = pd.read_csv(rf"{REFRESH}\klines_full.csv")
k["ts_s"] = (k.time_period_start_us // 1_000_000).astype("int64")
klines = {}
for a in ("BTC","ETH","SOL"):
    sub = k[k.symbol_id == ASSET_BIN[a]].sort_values("ts_s").reset_index(drop=True)
    klines[a] = sub[["ts_s","price_close"]].reset_index(drop=True)

def asof(a, ts):
    """End-time-indexed asof (1MIN bars). Avoids the bar-open-indexed
    lookahead bug fixed in extended_backtest_with_robustness 2026-05-06."""
    df = klines[a]
    end_us = (df.ts_s.astype("int64") + 60).values * 1_000_000
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    return float("nan") if idx < 0 else float(df.price_close.iloc[idx])

# Load universe
print("loading universe…")
m = pd.read_csv(rf"{REFRESH}\markets_full.csv")
r = pd.read_csv(rf"{REFRESH}\market_resolutions_full.csv")[["slug","outcome"]]
df = m.merge(r, on="slug", how="inner", suffixes=("_m",""))
df["outcome"] = df["outcome"].fillna(df.outcome_m)
df = df.dropna(subset=["outcome"])
df = df[df.ticker.isin(["BTC","ETH","SOL"]) & df.timeframe.isin(["5m","15m"])].copy()
df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
df["asset"] = df.ticker
df["window_s"] = df.timeframe.map({"5m":300,"15m":900})

print(f"\nuniverse: {len(df)} resolved markets")

# Sanity: if ws is market-start, then close@(ws+window) vs close@(ws) should match outcome
# For each market, compute the move under various candidate anchors
samples = df.sample(min(2000, len(df)), random_state=42).reset_index(drop=True)

anchors = {
    "ws":        lambda r: r.ws,
    "ws-60":     lambda r: r.ws - 60,
    "ws+60":     lambda r: r.ws + 60,
    "ws+120":    lambda r: r.ws + 120,
}
ends = {
    "ws+window": lambda r: r.ws + r.window_s,
    "ws":        lambda r: r.ws,
    "ws+window-60": lambda r: r.ws + r.window_s - 60,
}

print(f"\n=== Anchor pair vs outcome agreement on {len(samples)} markets (5m + 15m mixed) ===\n")
print(f"{'anchor':<12} {'end':<14} {'agreement %':>12} {'avg_move_up_only':>18}")
print("-" * 60)
for an, fa in anchors.items():
    for en, fe in ends.items():
        if an == en.split("+")[0] or (an=="ws" and en=="ws"):
            continue
        agree = 0; n = 0; up_move_when_up = []
        for r in samples.itertuples(index=False):
            p0 = asof(r.asset, fa(r)); p1 = asof(r.asset, fe(r))
            if not (math.isfinite(p0) and math.isfinite(p1) and p0>0): continue
            went_up = p1 > p0
            n += 1
            if (went_up and r.outcome=="Up") or (not went_up and r.outcome=="Down"):
                agree += 1
            if r.outcome=="Up":
                up_move_when_up.append((p1-p0)/p0*1e4)
        if n:
            up_avg = sum(up_move_when_up)/len(up_move_when_up) if up_move_when_up else 0
            print(f"{an:<12} {en:<14} {agree/n*100:>11.1f}% {up_avg:>+15.1f}bp  (n={n})")

# Also check: separate by timeframe
print(f"\n=== ws → ws+window split by tf ===\n")
for tf, ws_window in (("5m",300),("15m",900)):
    sub = samples[samples.timeframe==tf]
    agree = 0; n = 0
    for r in sub.itertuples(index=False):
        p0 = asof(r.asset, r.ws); p1 = asof(r.asset, r.ws+ws_window)
        if not (math.isfinite(p0) and math.isfinite(p1) and p0>0): continue
        n += 1
        went_up = p1 > p0
        if (went_up and r.outcome=="Up") or (not went_up and r.outcome=="Down"):
            agree += 1
    print(f"  {tf}: {agree}/{n} = {agree/n*100:.1f}% agreement (asset went UP from ws → ws+{ws_window} matches outcome)")

# Strike-price check: Polymarket UpDown strike is usually set at market open. Look at markets_full for hints.
print(f"\n=== markets_full sample row (full) ===\n")
print(df.iloc[0].to_dict())
