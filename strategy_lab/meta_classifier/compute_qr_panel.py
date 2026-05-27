"""Port TradingView 'Quantum Ribbon Lite' Pine v6 indicator to Python.

5-layer EMA ribbon spanning [ema_fast=21, ema_slow=60] with pair_width=7.
Spacing = (60 - 7 - 21) / 4 = 8.
  Layer 1: 21/28   Layer 2: 29/36   Layer 3: 37/44   Layer 4: 45/52   Layer 5: 53/60

Outputs per (asset, ts_us) on resampled 5m and 15m bars:
  asset, ts_us, bar_close_us  (= bar_start + tf - 1us)
  close, volume,
  ema_s1, ema_l1, ..., ema_s5, ema_l5,
  bull_align, bear_align, ribbon_state (-2..+2),
  bullish_emas, bearish_emas, ribbon_aligned (0/1),
  ribbon_expanding (0/1), current_spread, past_spread,
  bars_above, bars_below, price_consistent (0/1),
  market_regime (1=trending, 0=ranging),
  market_health (0..100), signal_confidence (0..8),
  volume_ratio, momentum_consistency (0..10).

Save:
  data/v4/canonical/_results/qr_panel_5m.parquet
  data/v4/canonical/_results/qr_panel_15m.parquet
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT5 = ROOT / "data" / "v4" / "canonical" / "_results" / "qr_panel_5m.parquet"
OUT15 = ROOT / "data" / "v4" / "canonical" / "_results" / "qr_panel_15m.parquet"

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}

# QR Lite EMA layer pairs (short, long)
LAYERS = [(21, 28), (29, 36), (37, 44), (45, 52), (53, 60)]
# Alignment weights per layer (Pine spec)
ALIGN_W = np.array([1.0, 1.2, 1.4, 1.6, 2.0])


def resample_1s_to_tf(df_asset: pd.DataFrame, tf_s: int) -> pd.DataFrame:
    """Resample 1s OHLCV → tf_s bars. Input cols: time_period_start_us,
    price_open, price_high, price_low, price_close, volume_traded.

    Output cols: ts_us (bar_start), open, high, low, close, volume.
    Bars aligned to wall-clock floor of tf_s seconds.
    """
    d = df_asset.sort_values("time_period_start_us").reset_index(drop=True)
    bar_start_us = (d["time_period_start_us"].astype("int64") // (tf_s * 1_000_000)) * (tf_s * 1_000_000)
    g = d.groupby(bar_start_us, sort=True)
    out = pd.DataFrame({
        "ts_us": g["time_period_start_us"].first().index.values.astype("int64"),
        "open":   g["price_open"].first().values,
        "high":   g["price_high"].max().values,
        "low":    g["price_low"].min().values,
        "close":  g["price_close"].last().values,
        "volume": g["volume_traded"].sum().fillna(0).values,
    }).reset_index(drop=True)
    return out


def compute_qr_for_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute Quantum Ribbon Lite features per bar."""
    bars = bars.sort_values("ts_us").reset_index(drop=True).copy()
    close = bars["close"].astype("float64")
    vol = bars["volume"].astype("float64").fillna(0.0)

    # 1. Compute 10 EMAs (5 pairs)
    emas = {}
    for i, (s, l) in enumerate(LAYERS, start=1):
        emas[f"ema_s{i}"] = close.ewm(span=s, adjust=False, min_periods=s).mean()
        emas[f"ema_l{i}"] = close.ewm(span=l, adjust=False, min_periods=l).mean()
        bars[f"ema_s{i}"] = emas[f"ema_s{i}"].values
        bars[f"ema_l{i}"] = emas[f"ema_l{i}"].values

    # 2. Alignment & ribbon state
    ms = np.column_stack([emas[f"ema_s{i}"].values for i in range(1, 6)])  # (N,5)
    ml = np.column_stack([emas[f"ema_l{i}"].values for i in range(1, 6)])  # (N,5)
    bull_mask = (ms >= ml)
    bear_mask = (ms < ml)
    bull_score = (bull_mask * ALIGN_W).sum(axis=1)
    bear_score = (bear_mask * ALIGN_W).sum(axis=1)
    total = bull_score + bear_score
    bull_align = np.where(total > 0, bull_score / np.where(total == 0, 1, total), 0.5)
    bars["bull_align"] = bull_align
    bars["bear_align"] = 1.0 - bull_align

    # ribbon_state int: -2=strong_bear, -1=bear, 0=neutral, +1=bull, +2=strong_bull
    state = np.zeros(len(bars), dtype=np.int8)
    state[bull_align >= 0.75] = 2
    state[(bull_align >= 0.60) & (bull_align < 0.75)] = 1
    state[(bull_align > 0.40) & (bull_align < 0.60)] = 0
    state[(bull_align > 0.25) & (bull_align <= 0.40)] = -1
    state[bull_align <= 0.25] = -2
    bars["ribbon_state"] = state

    # 3. Market regime (trending vs ranging)
    bullish_emas = bull_mask.sum(axis=1)
    bearish_emas = bear_mask.sum(axis=1)
    bars["bullish_emas"] = bullish_emas.astype(np.int8)
    bars["bearish_emas"] = bearish_emas.astype(np.int8)
    ribbon_aligned = ((bullish_emas >= 4) | (bearish_emas >= 4)).astype(np.int8)
    bars["ribbon_aligned"] = ribbon_aligned

    # current_spread = |ms1 - ml5|, past_spread = same 10 bars ago
    spread = np.abs(emas["ema_s1"].values - emas["ema_l5"].values)
    bars["current_spread"] = spread
    past_spread = np.roll(spread, 10)
    past_spread[:10] = np.nan
    bars["past_spread"] = past_spread
    ribbon_expanding = (spread > past_spread * 0.9).astype(np.int8)
    # NaN past_spread → 0 (don't trend until warmup complete)
    nan_mask = ~np.isfinite(past_spread)
    ribbon_expanding[nan_mask] = 0
    bars["ribbon_expanding"] = ribbon_expanding

    # ribbon_center = (ms1 + ml5) / 2, count last 10 bars above/below
    ribbon_center = (emas["ema_s1"].values + emas["ema_l5"].values) / 2.0
    above_ind = (close.values > ribbon_center).astype(np.int8)
    bars["bars_above"] = pd.Series(above_ind).rolling(10, min_periods=10).sum().values
    below_ind = (close.values < ribbon_center).astype(np.int8)
    bars["bars_below"] = pd.Series(below_ind).rolling(10, min_periods=10).sum().values
    bars["price_consistent"] = ((bars["bars_above"] >= 8) | (bars["bars_below"] >= 8)).fillna(False).astype(np.int8)

    # trending: ribbon_aligned AND price_consistent AND ribbon_expanding
    bars["market_regime"] = ((bars["ribbon_aligned"] == 1) &
                             (bars["price_consistent"] == 1) &
                             (bars["ribbon_expanding"] == 1)).astype(np.int8)

    # 4. Market health
    alignment_strength = np.maximum(bullish_emas, bearish_emas)
    # 40 if alignment==5, 30 if alignment==4, 20 else
    h_align = np.where(alignment_strength == 5, 40,
                       np.where(alignment_strength == 4, 30, 20))
    h_regime = np.where(bars["market_regime"].values == 1, 30, 15)
    # volume_ratio = volume / sma(volume,20)
    vol_sma20 = vol.rolling(20, min_periods=20).mean()
    volume_ratio = (vol / vol_sma20.replace(0, np.nan)).fillna(0)
    bars["volume_ratio"] = volume_ratio.values
    h_vol = np.where(volume_ratio.values > 1.1, 20, 10)
    # avg_spacing = (|ms1-ml1| + |ms5-ml5|) / 2
    avg_spacing = (np.abs(emas["ema_s1"].values - emas["ema_l1"].values) +
                   np.abs(emas["ema_s5"].values - emas["ema_l5"].values)) / 2.0
    normalized = np.where(close.values > 0, avg_spacing / close.values * 100.0, 0.0)
    h_spacing = np.where(normalized > 1.0, 10, np.where(normalized > 0.5, 5, 0))
    health = h_align + h_regime + h_vol + h_spacing
    bars["market_health"] = health.astype("float32")

    # 5. momentum_consistency = how many of last 10 bars share sign with current momentum
    # momentum = close - close[-10]
    momentum = close - close.shift(10)
    mom_sign = np.sign(momentum.values)
    mom_sign_now = pd.Series(mom_sign).rolling(1).apply(lambda x: x.iloc[-1], raw=False).values
    # Count of last 10 momentum signs matching current sign
    sign_match = np.full(len(bars), 0, dtype=np.int8)
    mom_sign_arr = mom_sign.copy()
    for k in range(len(bars)):
        if k < 9:
            sign_match[k] = 0
            continue
        cur = mom_sign_arr[k]
        if not np.isfinite(cur) or cur == 0:
            sign_match[k] = 0
            continue
        window = mom_sign_arr[k - 9:k + 1]
        sign_match[k] = int(np.sum(window == cur))
    bars["momentum_consistency"] = sign_match

    # 6. Signal confidence (0..8)
    conf = np.zeros(len(bars), dtype="float32")
    is_trending = bars["market_regime"].values == 1
    conf[is_trending & (health > 80)] += 4
    conf[is_trending & (health > 70) & (health <= 80)] += 3.5
    conf[is_trending & (health > 60) & (health <= 70)] += 3
    conf[is_trending & (health <= 60)] += 2
    conf[(~is_trending) & (health > 70)] += 3
    conf[(~is_trending) & (health > 50) & (health <= 70)] += 2
    conf[(~is_trending) & (health <= 50)] += 1
    # volume boost
    conf[volume_ratio.values > 1.3] += 1
    # momentum consistency boost
    conf[sign_match > 7] += 1
    # ribbon boost
    abs_state = np.abs(state)
    base_boost = np.where(abs_state == 2, 1.5, np.where(abs_state == 1, 0.9, 0.0))
    boost_mult = np.where(conf < 3.0, 1.5, 0.8)
    conf += base_boost * boost_mult
    conf = np.minimum(conf, 8.0)
    bars["signal_confidence"] = conf

    return bars


def compute_per_asset_tf(df: pd.DataFrame, tf_s: int) -> pd.DataFrame:
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = df[df.asset == asset]
        if len(sub) == 0:
            continue
        t0 = time.time()
        bars = resample_1s_to_tf(sub, tf_s)
        qr = compute_qr_for_bars(bars)
        qr["asset"] = asset
        qr["tf_s"] = tf_s
        # bar_close_us = ts_us + tf_s - 1 microsecond — for causal asof lookup
        qr["bar_close_us"] = qr["ts_us"].astype("int64") + (tf_s * 1_000_000) - 1
        cols_order = (
            ["asset", "tf_s", "ts_us", "bar_close_us",
             "open", "high", "low", "close", "volume"]
            + [f"ema_s{i}" for i in range(1, 6)]
            + [f"ema_l{i}" for i in range(1, 6)]
            + ["bull_align", "bear_align", "ribbon_state",
               "bullish_emas", "bearish_emas", "ribbon_aligned",
               "current_spread", "past_spread", "ribbon_expanding",
               "bars_above", "bars_below", "price_consistent",
               "market_regime", "market_health",
               "volume_ratio", "momentum_consistency", "signal_confidence"]
        )
        qr = qr[cols_order]
        parts.append(qr)
        print(f"  {asset} tf={tf_s}s: {len(qr):,} bars in {time.time()-t0:.1f}s")
    return pd.concat(parts, ignore_index=True)


def main():
    print(f"[1] loading 1s binance {KL1S.name}...")
    t0 = time.time()
    df = pd.read_parquet(KL1S)
    print(f"    {len(df):,} rows in {time.time()-t0:.1f}s")
    df = df.sort_values(["symbol_id", "time_period_start_us", "source"])
    df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df["asset"] = df["symbol_id"].map(SYM_MAP)
    df = df[df["asset"].notna()].copy()
    print(f"    after dedupe: {len(df):,}  assets: {df.asset.value_counts().to_dict()}")

    print("\n[2] computing 5m QR panel...")
    qr5 = compute_per_asset_tf(df, 300)
    OUT5.parent.mkdir(parents=True, exist_ok=True)
    qr5.to_parquet(OUT5, index=False, compression="zstd")
    import os
    print(f"  wrote {OUT5.name} ({os.path.getsize(OUT5)/1024/1024:.1f} MB, {len(qr5):,} rows)")

    print("\n[3] computing 15m QR panel...")
    qr15 = compute_per_asset_tf(df, 900)
    qr15.to_parquet(OUT15, index=False, compression="zstd")
    print(f"  wrote {OUT15.name} ({os.path.getsize(OUT15)/1024/1024:.1f} MB, {len(qr15):,} rows)")

    print("\n[4] state distribution (5m):")
    for asset in ("BTC", "ETH", "SOL"):
        sub = qr5[qr5.asset == asset]
        d = sub.ribbon_state.value_counts(normalize=True).sort_index()
        rg = sub.market_regime.mean()
        hh = sub.market_health.mean()
        cc = sub.signal_confidence.mean()
        print(f"  {asset} | state dist (-2..+2): {dict(zip(d.index.tolist(), d.round(3).tolist()))}")
        print(f"      regime_trending: {rg:.3f}  mean_health: {hh:.1f}  mean_conf: {cc:.2f}")

    print("\n[5] state distribution (15m):")
    for asset in ("BTC", "ETH", "SOL"):
        sub = qr15[qr15.asset == asset]
        d = sub.ribbon_state.value_counts(normalize=True).sort_index()
        rg = sub.market_regime.mean()
        hh = sub.market_health.mean()
        cc = sub.signal_confidence.mean()
        print(f"  {asset} | state dist (-2..+2): {dict(zip(d.index.tolist(), d.round(3).tolist()))}")
        print(f"      regime_trending: {rg:.3f}  mean_health: {hh:.1f}  mean_conf: {cc:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
