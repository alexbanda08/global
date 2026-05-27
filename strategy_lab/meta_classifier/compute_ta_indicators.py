"""Compute MA Ribbon + Slow Stochastic + BB + MFI + CCI per-1s-bar indicators.

Output: data/v4/canonical/_results/ta_indicators_1s.parquet

Schema (one row per (asset, ts_us)):
  asset, ts_us, close, volume, taker_buy_base,
  # MA Ribbon (EMA on close at periods 5,10,15,...,100):
  ema_5, ema_10, ema_15, ..., ema_100,
  # Ribbon-derived features (compact summary):
  ribbon_lead_slope_bps,    # 5s change in ema_5, in bps
  ribbon_lead_vs_ref_bps,   # (ema_5 - ema_100) / ema_100, in bps
  ribbon_alignment_pct,     # % of (ema_i > ema_{i+5}) pairs, 0-100
  ribbon_compression_bps,   # std(all 20 EMAs) / mean × 10000
  ribbon_color,             # 0=gray, 1=lime, 2=maroon, 3=red, 4=green (per Pine logic)
  # Slow Stochastic on 1s (length=14 bars × 60s rolling proxy):
  stoch_k_60s, stoch_d_60s,
  stoch_k_300s, stoch_d_300s,
  # Bollinger Bands at 60s and 120s:
  bb_pos_60s, bb_width_60s,
  bb_pos_120s, bb_width_120s,
  # Money Flow Index (60s + 300s):
  mfi_60s, mfi_300s,
  # CCI (60s):
  cci_60s
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "ta_indicators_1s.parquet"

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}

EMA_PERIODS = list(range(5, 105, 5))  # 5, 10, 15, ..., 100 → 20 EMAs


def slow_stoch(close, high, low, length=14, smooth_k=3, smooth_d=3):
    """Pine: k = SMA(stoch(close,high,low,length), smooth_k); d = SMA(k, smooth_d)"""
    ll = low.rolling(length, min_periods=length).min()
    hh = high.rolling(length, min_periods=length).max()
    raw_k = 100.0 * (close - ll) / (hh - ll).replace(0, np.nan)
    k = raw_k.rolling(smooth_k, min_periods=1).mean()
    d = k.rolling(smooth_d, min_periods=1).mean()
    return k, d


def bb_pos_width(close, length, stddev_mult=2.0):
    mid = close.rolling(length, min_periods=length).mean()
    std = close.rolling(length, min_periods=length).std()
    upper = mid + stddev_mult * std
    lower = mid - stddev_mult * std
    width = (upper - lower) / mid
    pos = (close - lower) / (upper - lower).replace(0, np.nan)
    return pos.clip(-0.5, 1.5), width


def mfi(close, high, low, volume, length):
    tp = (high + low + close) / 3.0
    mf = tp * volume
    tp_diff = tp.diff()
    pos_mf = mf.where(tp_diff > 0, 0.0).rolling(length, min_periods=length).sum()
    neg_mf = mf.where(tp_diff < 0, 0.0).rolling(length, min_periods=length).sum()
    ratio = pos_mf / neg_mf.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + ratio)


def cci(close, high, low, length):
    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(length, min_periods=length).mean()
    mean_dev = (tp - sma_tp).abs().rolling(length, min_periods=length).mean()
    return (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))


def compute_per_asset(df):
    """df has cols: time_period_start_us, price_close, price_high, price_low, volume_traded."""
    df = df.sort_values("time_period_start_us").reset_index(drop=True)
    close = df["price_close"]
    high = df["price_high"]
    low = df["price_low"]
    vol = df["volume_traded"].fillna(0)
    out = pd.DataFrame({
        "ts_us": df["time_period_start_us"].values.astype("int64"),
        "close": close.values,
        "volume": vol.values,
        "taker_buy_base": df.get("taker_buy_base", pd.Series([0.0]*len(df))).fillna(0).values,
    })

    # ----- EMA ribbon (20 EMAs) -----
    ema_cols = []
    ema_matrix = []
    for p in EMA_PERIODS:
        e = close.ewm(span=p, adjust=False, min_periods=p).mean()
        out[f"ema_{p}"] = e.values
        ema_cols.append(f"ema_{p}")
        ema_matrix.append(e.values)
    ema_matrix = np.array(ema_matrix)  # shape (20, N)

    # Ribbon-derived features
    ema_5_arr = ema_matrix[0]
    ema_100_arr = ema_matrix[-1]
    # Lead slope: 5s change in ema_5
    lead_slope = pd.Series(ema_5_arr).diff(5)
    out["ribbon_lead_slope_bps"] = (lead_slope.values / ema_5_arr) * 10000.0
    out["ribbon_lead_vs_ref_bps"] = ((ema_5_arr - ema_100_arr) / ema_100_arr) * 10000.0

    # Alignment %: count of (ema_i > ema_{i+5}) pairs / 19 (max possible)
    in_order = np.zeros(ema_matrix.shape[1], dtype=np.int16)
    for i in range(len(EMA_PERIODS) - 1):
        in_order += (ema_matrix[i] > ema_matrix[i + 1]).astype(np.int16)
    out["ribbon_alignment_pct"] = (in_order / (len(EMA_PERIODS) - 1)) * 100.0

    # Compression: std / mean × 10000 (across all 20 EMAs at each timestep)
    mean_emas = ema_matrix.mean(axis=0)
    std_emas = ema_matrix.std(axis=0)
    out["ribbon_compression_bps"] = (std_emas / mean_emas) * 10000.0

    # Ribbon color (per Pine code):
    # lime: change(ma05)>=0 AND ma05>ma100   (UP-trending, in uptrend zone)
    # maroon: change(ma05)<0 AND ma05>ma100  (DOWN-tick, but still in uptrend zone)
    # red: change(ma05)<=0 AND ma05<ma100    (DOWN-trending, in downtrend zone)
    # green: change(ma05)>=0 AND ma05<ma100  (UP-tick, but still in downtrend zone)
    slope_pos = (lead_slope >= 0).values
    above_ref = (ema_5_arr > ema_100_arr)
    color = np.full(len(out), 0, dtype=np.int8)  # default gray
    color[slope_pos & above_ref] = 1   # lime
    color[(~slope_pos) & above_ref] = 2  # maroon
    color[(~slope_pos) & (~above_ref)] = 3  # red
    color[slope_pos & (~above_ref)] = 4  # green
    out["ribbon_color"] = color

    # ----- Slow Stochastic at multiple windows -----
    for win in (60, 300):
        k, d = slow_stoch(close, high, low, length=win, smooth_k=3, smooth_d=3)
        out[f"stoch_k_{win}s"] = k.values
        out[f"stoch_d_{win}s"] = d.values

    # ----- Bollinger Bands -----
    for win in (60, 120):
        pos, width = bb_pos_width(close, length=win)
        out[f"bb_pos_{win}s"] = pos.values
        out[f"bb_width_{win}s"] = width.values

    # ----- MFI -----
    for win in (60, 300):
        out[f"mfi_{win}s"] = mfi(close, high, low, vol, length=win).values

    # ----- CCI -----
    out["cci_60s"] = cci(close, high, low, length=60).values

    return out


def main():
    print(f"[1] loading 1s binance {KL1S.name}...")
    t0 = time.time()
    df = pd.read_parquet(KL1S)
    print(f"    {len(df):,} rows in {time.time()-t0:.1f}s")

    # Dedupe + add asset col
    df = df.sort_values(["symbol_id", "time_period_start_us", "source"])
    df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df["asset"] = df["symbol_id"].map(SYM_MAP)
    df = df[df["asset"].notna()].copy()
    print(f"    after dedupe: {len(df):,}  assets: {df.asset.value_counts().to_dict()}")

    out_per_asset = []
    for asset in ("BTC", "ETH", "SOL"):
        t0 = time.time()
        sub = df[df["asset"] == asset]
        ind = compute_per_asset(sub)
        ind["asset"] = asset
        # reorder
        cols = ["asset", "ts_us"] + [c for c in ind.columns if c not in ("asset", "ts_us")]
        ind = ind[cols]
        print(f"    {asset}: computed indicators on {len(ind):,} bars in {time.time()-t0:.1f}s")
        out_per_asset.append(ind)

    all_ind = pd.concat(out_per_asset, ignore_index=True)
    all_ind = all_ind.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"[2] writing {OUT}...")
    all_ind.to_parquet(OUT, index=False, compression="zstd")
    import os
    print(f"    wrote {os.path.getsize(OUT)/1024/1024:.1f} MB")

    print("\n[3] sanity check — first few BTC rows with ribbon features (skip warmup):")
    sample = all_ind[(all_ind.asset == "BTC")].iloc[110:115]
    show = ["asset", "ts_us", "close", "ribbon_lead_slope_bps", "ribbon_lead_vs_ref_bps",
            "ribbon_alignment_pct", "ribbon_compression_bps", "ribbon_color",
            "stoch_k_60s", "bb_pos_60s", "mfi_60s", "cci_60s"]
    print(sample[show].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
