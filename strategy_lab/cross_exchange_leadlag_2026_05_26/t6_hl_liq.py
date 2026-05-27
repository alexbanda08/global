"""TASK 6 — Hyperliquid liquidation cascades as direction/volatility signal."""
from __future__ import annotations
import sys
from pathlib import Path
import warnings; warnings.filterwarnings("ignore")

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines_1s, load_hyperliquid_liquidations

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"

WIN_START_US = int(pd.Timestamp("2026-05-01", tz="UTC").value // 1000)
WIN_END_US   = int(pd.Timestamp("2026-05-16 06:00", tz="UTC").value // 1000)

def binance_arr(asset):
    df = load_klines_1s(asset=asset)
    df = df[(df.time_period_start_us >= WIN_START_US - 600_000_000) & (df.time_period_start_us <= WIN_END_US + 600_000_000)]
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    return (df.time_period_start_us.values + 1_000_000).astype("int64"), df.price_close.astype("float64").values

# For each liquidation event, compute binance forward return at 5s, 30s, 60s
# Also check if the liquidation SIDE (long-liq → downward forcing? or short-liq → up?) predicts direction
rows = []
for asset in ["BTC","ETH","SOL"]:
    print(f"\n=== {asset} ===", flush=True)
    liqs = load_hyperliquid_liquidations(asset=asset)
    liqs = liqs[(liqs.time_exchange_us >= WIN_START_US) & (liqs.time_exchange_us <= WIN_END_US - 600_000_000)]
    print(f"  liqs: {len(liqs):,}")
    print(f"  liq columns: {liqs.columns.tolist()}")
    if "side" in liqs.columns:
        print(f"  liq side counts: {liqs.side.value_counts().to_dict()}")
    bn_end, bn_px = binance_arr(asset)

    # Compute forward returns
    for fwd_s in [5, 30, 60, 120, 300]:
        liq_t = liqs.time_exchange_us.values.astype("int64")
        p_now = np.full(len(liq_t), np.nan)
        p_fwd = np.full(len(liq_t), np.nan)
        idx_now = np.searchsorted(bn_end, liq_t, side="right") - 1
        idx_fwd = np.searchsorted(bn_end, liq_t + fwd_s*1_000_000, side="right") - 1
        valid = (idx_now >= 0) & (idx_fwd >= 0) & (idx_fwd < len(bn_px))
        p_now[valid] = bn_px[idx_now[valid]]
        p_fwd[valid] = bn_px[idx_fwd[valid]]
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.log(p_fwd / p_now)
        ret = ret[np.isfinite(ret)]
        if len(ret) == 0: continue
        rows.append({"asset": asset, "fwd_s": fwd_s, "n": len(ret),
                     "mean_ret_bps": float(np.mean(ret) * 10000),
                     "std_ret_bps": float(np.std(ret) * 10000),
                     "P_up": float((ret > 0).mean()),
                     "abs_mean_bps": float(np.mean(np.abs(ret)) * 10000)})

        # Compare to baseline P_up (random sec)
        # Sample matching count of random times
        np.random.seed(0)
        rand_t = (np.random.uniform(WIN_START_US, WIN_END_US - fwd_s*1_000_000, size=len(liq_t))).astype("int64")
        i_n = np.searchsorted(bn_end, rand_t, side="right") - 1
        i_f = np.searchsorted(bn_end, rand_t + fwd_s*1_000_000, side="right") - 1
        v = (i_n >= 0) & (i_f >= 0) & (i_f < len(bn_px))
        with np.errstate(invalid="ignore", divide="ignore"):
            r_base = np.log(bn_px[i_f[v]] / bn_px[i_n[v]])
        r_base = r_base[np.isfinite(r_base)]
        if len(r_base) > 0:
            rows[-1]["baseline_P_up"] = float((r_base > 0).mean())
            rows[-1]["baseline_abs_mean_bps"] = float(np.mean(np.abs(r_base)) * 10000)
            rows[-1]["vol_lift_x"] = rows[-1]["abs_mean_bps"] / rows[-1]["baseline_abs_mean_bps"] if rows[-1]["baseline_abs_mean_bps"] > 0 else None

    # Test: does liq side predict direction? Side='SHORT' (short-liquidation = forced buy) => UP
    if "side" in liqs.columns:
        # Aggregate liqs per 60s second-bucket
        liqs2 = liqs.copy()
        liqs2["bucket_s"] = liqs2.time_exchange_us // 60_000_000
        # HL side: 'B'=Buy (liquidator buys, so liquidated SHORT → bullish), 'A'=Ask/Sell (liquidated LONG → bearish)
        liqs2["long_liq"] = (liqs2.side == "A").astype(int)
        liqs2["short_liq"] = (liqs2.side == "B").astype(int)
        # Per bucket count
        per_bucket = liqs2.groupby("bucket_s").agg({"long_liq":"sum","short_liq":"sum"}).reset_index()
        per_bucket["net_short_minus_long"] = per_bucket.short_liq - per_bucket.long_liq
        # Look at 60s forward return per bucket
        bucket_t = (per_bucket.bucket_s * 60_000_000).astype("int64").values
        for fwd_s in [60, 120, 300]:
            idx_n = np.searchsorted(bn_end, bucket_t, side="right") - 1
            idx_f = np.searchsorted(bn_end, bucket_t + fwd_s*1_000_000, side="right") - 1
            v = (idx_n >= 0) & (idx_f >= 0) & (idx_f < len(bn_px))
            with np.errstate(invalid="ignore", divide="ignore"):
                ret = np.log(bn_px[idx_f[v]] / bn_px[idx_n[v]])
            net = per_bucket.net_short_minus_long.values[v]
            # only keep finite
            ok = np.isfinite(ret)
            ret = ret[ok]; net = net[ok]
            if len(ret) < 100: continue
            # Buckets with extreme net values
            pos_mask = net > np.quantile(net, 0.9)
            neg_mask = net < np.quantile(net, 0.1)
            if pos_mask.sum() > 0 and neg_mask.sum() > 0:
                rows.append({"asset": asset, "fwd_s": fwd_s, "kind": "net_short_extreme_pos",
                             "n": int(pos_mask.sum()),
                             "P_up": float((ret[pos_mask] > 0).mean()),
                             "mean_ret_bps": float(np.mean(ret[pos_mask]) * 10000)})
                rows.append({"asset": asset, "fwd_s": fwd_s, "kind": "net_short_extreme_neg",
                             "n": int(neg_mask.sum()),
                             "P_up": float((ret[neg_mask] > 0).mean()),
                             "mean_ret_bps": float(np.mean(ret[neg_mask]) * 10000)})

res = pd.DataFrame(rows)
res.to_csv(OUT_DIR / "_hl_liq_signal.csv", index=False)
print(res.to_string(index=False))
