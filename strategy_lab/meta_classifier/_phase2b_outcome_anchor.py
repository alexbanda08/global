"""Phase 2b: verify outcome anchor under slug-ws=END interpretation.

For each market in markets_full + market_resolutions_full, test:
  outcome = "Up" iff close@(end) > close@(strike)
where strike = slug_ws - window (= slug_ws - 300 for 5m, slug_ws - 900 for 15m)
and end = slug_ws.

Compare to my old assumption: slug_ws was bar-close start, outcome anchored
at (slug_ws-60, slug_ws + window - 60) — which gave 95.8% agreement.

Under new interpretation: outcome anchored at (slug_ws - window, slug_ws).
"""
import math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")

# Load VPS3 klines (the production data source)
print("loading klines...")
k = pd.read_csv(ROOT / "data/v4/refresh_2026_05_09/vps3_binance_klines.csv")
k["ts_s"] = (k.time_period_start_us // 1_000_000).astype("int64")
ASSET = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
klines = {}
for asset, sym in ASSET.items():
    sub = k[k.symbol_id == sym].sort_values("ts_s").drop_duplicates("ts_s").reset_index(drop=True)
    klines[asset] = (
        (sub.ts_s.values.astype("int64") + 60) * 1_000_000,
        sub.price_close.values.astype("float64"),
    )

def asof_strict(asset, ts_s):
    end_us, p = klines[asset]
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(p[idx])

# Universe
m_old = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv", dtype={"condition_id": str})
m_new = pd.read_csv(ROOT / "data/v4/refresh_2026_05_09/markets_full.csv", dtype={"condition_id": str})
r_old = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/market_resolutions_full.csv")[["slug","outcome"]]
r_new = pd.read_csv(ROOT / "data/v4/refresh_2026_05_09/market_resolutions_full.csv")[["slug","outcome"]]
m = pd.concat([m_old, m_new]).drop_duplicates("slug")
r = pd.concat([r_old, r_new]).drop_duplicates("slug")
df = m.merge(r, on="slug", how="inner", suffixes=("_m","")).copy()
df = df.dropna(subset=["outcome"])
df = df[df.ticker.isin(["BTC","ETH","SOL"]) & df.timeframe.isin(["5m","15m"])].copy()
df["asset"] = df.ticker
df["tf"] = df.timeframe
df["window_s"] = df.tf.map({"5m": 300, "15m": 900})
df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
print(f"resolved markets: {len(df)}\n")

# Test ONLY anchors based on slug-ws=END interpretation
# Under slug-ws=END: market = (ws-window, ws). Strike = ws-window. End = ws.
# Outcome = "Up" iff close@end > close@strike.
print("=== Outcome anchor agreement test (under slug-ws=END semantics) ===\n")
print(f"{'anchor (start, end)':<35} {'agreement %':>13} {'n':>6}")
print("-" * 60)
candidates = [
    ("strike, end", lambda r: (r.ws - r.window_s, r.ws)),
    ("strike-60, end-60", lambda r: (r.ws - r.window_s - 60, r.ws - 60)),
    ("strike+60, end+60", lambda r: (r.ws - r.window_s + 60, r.ws + 60)),
    ("strike, end-60", lambda r: (r.ws - r.window_s, r.ws - 60)),
    ("strike+60, end-60", lambda r: (r.ws - r.window_s + 60, r.ws - 60)),
    ("strike-60, end (old test winner)", lambda r: (r.ws - 60, r.ws + r.window_s - 60)),  # old (ws-60, ws+window-60)
]
for name, fn in candidates:
    agree = 0; n = 0
    for r in df.itertuples(index=False):
        s, e = fn(r)
        p0 = asof_strict(r.asset, s); p1 = asof_strict(r.asset, e)
        if not (math.isfinite(p0) and math.isfinite(p1) and p0 > 0):
            continue
        n += 1
        went_up = p1 > p0
        actual_up = (r.outcome == "Up")
        if went_up == actual_up:
            agree += 1
    if n:
        print(f"{name:<35} {100*agree/n:>11.1f}% {n:>6}")

# Also break down per (asset, tf) for the best anchor
print("\n=== Per (asset, tf) agreement under (strike, end) anchor ===\n")
print(f"{'asset':<5} {'tf':<5} {'n':>6} {'agree %':>10}")
for (a, tf), g in df.groupby(["asset", "tf"]):
    agree = 0; n = 0
    for r in g.itertuples(index=False):
        p0 = asof_strict(r.asset, r.ws - r.window_s)
        p1 = asof_strict(r.asset, r.ws)
        if not (math.isfinite(p0) and math.isfinite(p1) and p0 > 0):
            continue
        n += 1
        went_up = p1 > p0
        actual_up = (r.outcome == "Up")
        if went_up == actual_up:
            agree += 1
    if n:
        print(f"{a:<5} {tf:<5} {n:>6} {100*agree/n:>9.1f}%")
