"""Phase 2: brute-force find production's actual ret_2m anchor using VPS3 klines.

For each of 300 production audit rows with `ret_2m_at_signal`, compute ret_2m
across 11×11 (a, b) anchor pairs in {-300,-240,-180,-120,-60,0,60,120,180,240,300}.
Find the pair that minimizes residual on the most rows.
"""
import math
import re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")
KLINES = ROOT / "data/v4/refresh_2026_05_09/vps3_binance_klines.csv"
LIVE = ROOT / "data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv"

# Load klines per asset
print("loading VPS3 binance klines...")
k = pd.read_csv(KLINES)
k["ts_s"] = (k.time_period_start_us // 1_000_000).astype("int64")
ASSET = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
klines = {}
for asset, sym in ASSET.items():
    sub = k[k.symbol_id == sym].sort_values("ts_s").drop_duplicates("ts_s").reset_index(drop=True)
    klines[asset] = (
        (sub.ts_s.values.astype("int64") + 60) * 1_000_000,  # end_us
        sub.ts_s.values.astype("int64") * 1_000_000,           # start_us
        sub.price_close.values.astype("float64"),
    )
    print(f"  {asset}: {len(sub)} bars, {sub.ts_s.min()} -> {sub.ts_s.max()}")

def asof_strict(asset, ts_s):
    end_us, _, p = klines[asset]
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(p[idx])

def asof_buggy(asset, ts_s):
    """bar-start-indexed: returns close of bar OPENING at ts_s (close 60s in future)."""
    _, start_us, p = klines[asset]
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(start_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(p[idx])

# Load production audit + slug -> ws
sig = pd.read_csv(LIVE, dtype={"condition_id": str})
sig = sig.dropna(subset=["condition_id", "ret_2m_at_signal"])
SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_(HOLD|HEDGE|SELL)$")
sig["asset"] = sig.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(1).upper() if SLEEVE_RE.match(s) else None)
sig["is_v2"] = sig.sleeve_id.apply(lambda s: bool(SLEEVE_RE.match(s).group(3)) if SLEEVE_RE.match(s) else False)
sig["tf_p"] = sig.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(2) if SLEEVE_RE.match(s) else None)
sig = sig.dropna(subset=["asset"])

m_old = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
m_new = pd.read_csv(ROOT / "data/v4/refresh_2026_05_09/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
mk = pd.concat([m_old, m_new]).drop_duplicates("condition_id")
sig = sig.merge(mk, on="condition_id", how="left").dropna(subset=["slug"])
sig["ws"] = sig.slug.str.extract(r"-(\d+)$")[0].astype("int64")
print(f"\nproduction audit rows w/ slug+ws: {len(sig)}")
print(f"  v1 5m: {((~sig.is_v2) & (sig.tf_p=='5m')).sum()}")
print(f"  v1 15m: {((~sig.is_v2) & (sig.tf_p=='15m')).sum()}")
print(f"  v2 5m: {(sig.is_v2 & (sig.tf_p=='5m')).sum()}")
print(f"  v2 15m: {(sig.is_v2 & (sig.tf_p=='15m')).sum()}")

# Brute force across all (a, b) offset pairs
offsets = [-960, -900, -840, -780, -720, -660, -600, -540, -480, -420,
           -360, -300, -240, -180, -120, -60, 0, 60, 120, 180, 240, 300]

def evaluate(off0, off1, asof_fn, df):
    rets = []
    for r in df.itertuples(index=False):
        c0 = asof_fn(r.asset, int(r.ws) + off0)
        c1 = asof_fn(r.asset, int(r.ws) + off1)
        if math.isfinite(c0) and math.isfinite(c1) and c0 > 0:
            rets.append(math.log(c1 / c0))
        else:
            rets.append(float("nan"))
    rets = np.array(rets)
    obs = df.ret_2m_at_signal.values.astype(float)
    valid = ~np.isnan(rets) & ~np.isnan(obs)
    if valid.sum() == 0:
        return float("inf"), 0
    diffs = np.abs(rets[valid] - obs[valid])
    return float(np.mean(diffs)), int(valid.sum())

# Run brute force separately for v1 5m, v1 15m, v2 5m, v2 15m
print("\n=== Brute force per (version, tf) ===\n")
for is_v2 in (False, True):
    for tf in ("5m", "15m"):
        sub = sig[(sig.is_v2 == is_v2) & (sig.tf_p == tf)]
        if len(sub) < 5:
            continue
        ver = "v2" if is_v2 else "v1"
        print(f"\n--- {ver} {tf} (n={len(sub)}) ---")
        results = []
        for kind, fn in (("strict", asof_strict), ("buggy", asof_buggy)):
            for off0 in offsets:
                for off1 in offsets:
                    if off0 == off1:
                        continue
                    mad, n = evaluate(off0, off1, fn, sub)
                    if math.isfinite(mad):
                        results.append((mad, off0, off1, kind, n))
        results.sort()
        print(f"  Top 5 (mad / off0 / off1 / kind):")
        for r in results[:5]:
            print(f"    MAD={r[0]:.6f}  ({r[1]:>4}, {r[2]:>4})  {r[3]}  n_valid={r[4]}")
        # Best
        best_mad, best_off0, best_off1, best_kind, _ = results[0]
        # Apply to full sub, count exact matches (within 1e-6)
        diffs = []
        asof_fn = asof_strict if best_kind == "strict" else asof_buggy
        for r in sub.itertuples(index=False):
            c0 = asof_fn(r.asset, int(r.ws) + best_off0)
            c1 = asof_fn(r.asset, int(r.ws) + best_off1)
            if math.isfinite(c0) and math.isfinite(c1) and c0 > 0:
                ret = math.log(c1 / c0)
                diffs.append(abs(ret - r.ret_2m_at_signal))
        if diffs:
            diffs = np.array(diffs)
            print(f"  Best config matches:")
            print(f"    within 1e-7: {int((diffs < 1e-7).sum())}/{len(diffs)}")
            print(f"    within 1e-5: {int((diffs < 1e-5).sum())}/{len(diffs)}")
            print(f"    within 1e-4: {int((diffs < 1e-4).sum())}/{len(diffs)}")
            print(f"    within 1e-3: {int((diffs < 1e-3).sum())}/{len(diffs)}")
