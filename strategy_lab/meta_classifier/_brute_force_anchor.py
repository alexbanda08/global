"""Brute-force search over (anchor_start_offset, anchor_end_offset, source) to find what
production actually computes for ret_2m_at_signal.
"""
import math
import re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")
LIVE = ROOT / "data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv"
KLINES = ROOT / "data/v4/refresh_2026_05_09/klines_full.csv"

sig = pd.read_csv(LIVE, dtype={"condition_id": str})
sig = sig.dropna(subset=["condition_id", "ret_2m_at_signal"])
SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_(HOLD|HEDGE|SELL)$")
sig["asset"] = sig.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(1).upper() if SLEEVE_RE.match(s) else None)
sig["is_v2"] = sig.sleeve_id.apply(lambda s: bool(SLEEVE_RE.match(s).group(3)) if SLEEVE_RE.match(s) else False)

markets_old = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
markets_new = pd.read_csv(ROOT / "data/v4/refresh_2026_05_09/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
markets = pd.concat([markets_old, markets_new]).drop_duplicates("condition_id")
sig = sig.merge(markets, on="condition_id", how="left")
sig = sig.dropna(subset=["slug"]).copy()
sig["ws"] = sig.slug.str.extract(r"-(\d+)$")[0].astype("int64")
print(f"sample size: {len(sig)}")

# Load BOTH binance and OKX separately
ASSET_BIN = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC": "OKX_SPOT_BTC_USDT", "ETH": "OKX_SPOT_ETH_USDT", "SOL": "OKX_SPOT_SOL_USDT"}
df_k = pd.read_csv(KLINES)
df_k["ts_s"] = (df_k.time_period_start_us // 1_000_000).astype("int64")
klines = {}  # (asset, source) -> (end_us, start_us, price_close)
for a in ("BTC", "ETH", "SOL"):
    for src_kind, sym in (("binance", ASSET_BIN[a]), ("okx", ASSET_OKX[a])):
        c = df_k[df_k.symbol_id == sym][["ts_s", "price_close"]].sort_values("ts_s").drop_duplicates("ts_s").reset_index(drop=True)
        if len(c):
            klines[(a, src_kind)] = (
                (c.ts_s.values.astype("int64") + 60) * 1_000_000,
                c.ts_s.values.astype("int64") * 1_000_000,
                c.price_close.values.astype("float64"),
            )

def asof_strict(asset, src, ts_s):
    rec = klines.get((asset, src))
    if rec is None:
        return float("nan")
    end_us, _, price_close = rec
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(price_close[idx])

def asof_buggy(asset, src, ts_s):
    rec = klines.get((asset, src))
    if rec is None:
        return float("nan")
    _, start_us, price_close = rec
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(start_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(price_close[idx])

# --- Brute-force search ---
# offsets in seconds: ±240s in 30s steps for both anchors
offsets = list(range(-240, 241, 30))
sources = ["binance", "okx"]
asof_kinds = ["strict", "buggy"]

print("brute-force search across", len(offsets), "× ", len(offsets), "anchor offsets × 2 sources × 2 asof types =",
      len(offsets) * len(offsets) * len(sources) * len(asof_kinds), "candidate configs")
print("(this picks the config with lowest mean-abs-diff to obs across", len(sig), "rows)")
print()

# To save time, sample 50 rows
sample = sig.sample(min(80, len(sig)), random_state=42).reset_index(drop=True)
obs_arr = sample.ret_2m_at_signal.values
n_sample = len(sample)

def compute_diffs(off0, off1, src, kind):
    asof_fn = asof_strict if kind == "strict" else asof_buggy
    rets = np.full(n_sample, np.nan)
    for i, r in enumerate(sample.itertuples(index=False)):
        c0 = asof_fn(r.asset, src, int(r.ws) + off0)
        c1 = asof_fn(r.asset, src, int(r.ws) + off1)
        if math.isfinite(c0) and math.isfinite(c1) and c0 > 0:
            rets[i] = math.log(c1 / c0)
    return np.nanmean(np.abs(rets - obs_arr)), rets

results = []
for src in sources:
    for kind in asof_kinds:
        for off0 in offsets:
            for off1 in offsets:
                if off0 == off1:
                    continue
                mad, _ = compute_diffs(off0, off1, src, kind)
                if math.isfinite(mad):
                    results.append((mad, off0, off1, src, kind))

results.sort()
print("=== Top 15 (anchor_start, anchor_end, source, asof) by lowest MAD on sample ===")
print(f"{'MAD':>10}  {'off0':>5} {'off1':>5} {'source':>8} {'kind':>8}")
for r in results[:15]:
    print(f"  {r[0]:.6f}  {r[1]:>5} {r[2]:>5} {r[3]:>8} {r[4]:>8}")

# Best config — apply to full set
best_mad, off0, off1, src, kind = results[0]
print(f"\n=== Best config: off0={off0}s, off1={off1}s, source={src}, asof={kind}, MAD={best_mad:.6f} ===")
asof_fn = asof_strict if kind == "strict" else asof_buggy
diffs_full = []
for r in sig.itertuples(index=False):
    c0 = asof_fn(r.asset, src, int(r.ws) + off0)
    c1 = asof_fn(r.asset, src, int(r.ws) + off1)
    if math.isfinite(c0) and math.isfinite(c1) and c0 > 0:
        ret = math.log(c1 / c0)
        diffs_full.append(abs(ret - r.ret_2m_at_signal))
print(f"full-sample MAD with best config: {np.mean(diffs_full):.6f}")
print(f"matches within 1e-5: {sum(d < 1e-5 for d in diffs_full)}/{len(diffs_full)}")
print(f"matches within 1e-4: {sum(d < 1e-4 for d in diffs_full)}/{len(diffs_full)}")
print(f"matches within 1e-3: {sum(d < 1e-3 for d in diffs_full)}/{len(diffs_full)}")
