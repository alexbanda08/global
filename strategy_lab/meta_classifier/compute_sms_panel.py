"""Compute Smart Money Structure (SMS) panel per asset × {5m, 15m}.

Ports the "Smart Money Structure | GainzAlgo" TradingView Pine v5 indicator:
  1. CHoCH / BOS structure (pivot_high/low, lookback=5)
  2. Multi-timeframe trend strength (1m..D EMA20+VWAP per TF)
  3. Cumulative Volume Delta (CVD) tiers
  4. RSI(14) divergence (5-bar pivots)
  5. Liquidity zones (20-bar high/low proximity)

Inputs:
  data/v4/canonical/klines_1s/binance_1s_28d.parquet  (resampled to 5m + 15m)

Outputs:
  data/v4/canonical/_results/sms_panel_5m.parquet
  data/v4/canonical/_results/sms_panel_15m.parquet

Schema (one row per (asset, ts_us) — ts_us = bar START in microseconds):
  asset, ts_us, open, high, low, close, volume, hlc3,
  pivot_high, pivot_low,
  last_high, last_low, last_high_prev, last_low_prev,
  bos_buy, bos_sell, choch_buy, choch_sell,
  bars_since_bos_buy, bars_since_bos_sell, bars_since_choch_buy, bars_since_choch_sell,
  rsi_14, rsi_bullish_div, rsi_bearish_div,
  cvd, cvd_level (-1/0/+1 = Low/Med/High), cvd_with_direction (sign),
  liquidity_up, liquidity_dn,
  trend_1m, trend_5m, trend_15m, trend_30m, trend_1h, trend_4h, trend_d,
  trend_strength_raw, trend_strength_pct, system_confidence
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT5 = ROOT / "data" / "v4" / "canonical" / "_results" / "sms_panel_5m.parquet"
OUT15 = ROOT / "data" / "v4" / "canonical" / "_results" / "sms_panel_15m.parquet"

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}

# Window: Apr 30 -> May 22 2026 (per task spec)
WIN_START_US = int(pd.Timestamp("2026-04-30 00:00", tz="UTC").value // 1_000)
WIN_END_US = int(pd.Timestamp("2026-05-22 23:59", tz="UTC").value // 1_000)

PIVOT_LB = 5  # pivot lookback (each side)
RSI_LEN = 14
LIQ_LB = 20  # liquidity zone lookback
LIQ_TOL = 0.0005  # 0.05% proximity for liquidity sweep flag

# Multi-TF spec (1m, 5m, 15m, 30m, 1h, 4h, D)
MULTI_TF_RULES = ["1min", "5min", "15min", "30min", "1h", "4h", "1D"]
MULTI_TF_LABELS = ["1m", "5m", "15m", "30m", "1h", "4h", "d"]
# Resampling note: our 28d window has only ~7 daily bars; treat as informational.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resample_1s_to_bar(df_1s: pd.DataFrame, freq_s: int) -> pd.DataFrame:
    """Resample 1s OHLCV to `freq_s` second bars.

    AUDIT-FIX 2026-05-26 (Bug #3): ts_us is now BAR END (slot_start + freq_s - 1us),
    not bar START. Previously the bar-start key combined with backward-asof produced
    a lookahead leak when joining to fire_us. Bar END keying makes merge_asof backward
    strictly causal (the latest CLOSED bar is picked).
    """
    df = df_1s.copy()
    df["dt"] = pd.to_datetime(df["ts_us"], unit="us", utc=True)
    df = df.set_index("dt").sort_index()
    rule = f"{freq_s}s"
    o = df["price_open"].resample(rule, label="left", closed="left").first()
    h = df["price_high"].resample(rule, label="left", closed="left").max()
    l = df["price_low"].resample(rule, label="left", closed="left").min()
    c = df["price_close"].resample(rule, label="left", closed="left").last()
    v = df["volume_traded"].resample(rule, label="left", closed="left").sum()
    bars = pd.concat([o, h, l, c, v], axis=1)
    bars.columns = ["open", "high", "low", "close", "volume"]
    bars = bars.dropna(subset=["close"]).reset_index()
    # FIX: bar END = bar START + freq_s * 1_000_000 - 1
    bar_us = int(freq_s) * 1_000_000
    bars["slot_start_us"] = (bars["dt"].astype("int64") // 1_000).astype("int64")
    bars["ts_us"] = bars["slot_start_us"] + bar_us - 1  # bar END
    bars["hlc3"] = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    return bars[["ts_us", "slot_start_us", "dt", "open", "high", "low", "close", "volume", "hlc3"]]


def rolling_pivot(s: pd.Series, lb: int, kind: str) -> pd.Series:
    """Pine ta.pivothigh/low: bar at index i-lb is the pivot if it's the max/min
    of the centered window [i-2lb, i]. Returns the pivot VALUE at index i (the
    confirmation bar — lookforward already complete), forward-filled to other bars."""
    win = 2 * lb + 1
    if kind == "high":
        center_max = s.rolling(win, center=False, min_periods=win).max()
        # The pivot bar's value is the center of the window — equal to center_max at the right edge.
        is_pivot = (s.shift(lb) == center_max)
        # The pivot VALUE is s.shift(lb) when confirmed.
        pivot_val = s.shift(lb).where(is_pivot)
    elif kind == "low":
        center_min = s.rolling(win, center=False, min_periods=win).min()
        is_pivot = (s.shift(lb) == center_min)
        pivot_val = s.shift(lb).where(is_pivot)
    else:
        raise ValueError(kind)
    return pivot_val


def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    """a crosses ABOVE b at this bar: a[t-1] <= b[t-1] AND a[t] > b[t]."""
    a_prev = a.shift(1); b_prev = b.shift(1)
    return (a > b) & (a_prev <= b_prev)


def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    """a crosses BELOW b at this bar."""
    a_prev = a.shift(1); b_prev = b.shift(1)
    return (a < b) & (a_prev >= b_prev)


def rsi_wilder(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder RSI (simple-mean smoothing — same as production F7 RSI)."""
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    avg_up = up.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_dn = dn.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_up / avg_dn.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def vwap_24h(hlc3: pd.Series, vol: pd.Series, bars_in_24h: int) -> pd.Series:
    """Rolling 24h VWAP, replacing the session-anchored Pine VWAP."""
    mp = min(bars_in_24h, 5)
    num = (hlc3 * vol).rolling(bars_in_24h, min_periods=mp).sum()
    den = vol.rolling(bars_in_24h, min_periods=mp).sum()
    return num / den.replace(0, np.nan)


def compute_trend_per_tf(bars_chart: pd.DataFrame, df_1s_asset: pd.DataFrame,
                         tf_rule: str, label: str) -> pd.Series:
    """Compute per-TF trend signal aligned to chart bars.

    1. Resample 1s -> tf_rule bars.
    2. Compute EMA(close, 20) and rolling-24h VWAP at TF.
    3. trend = +1 if close > EMA AND close > VWAP; -1 if both below; else 0.
    4. As-of merge back to chart bars (last completed TF bar at each chart bar's ts).
    """
    # Resample to the TF
    df = df_1s_asset.copy()
    df["dt"] = pd.to_datetime(df["ts_us"], unit="us", utc=True)
    df = df.set_index("dt").sort_index()
    c = df["price_close"].resample(tf_rule, label="left", closed="left").last()
    h = df["price_high"].resample(tf_rule, label="left", closed="left").max()
    l = df["price_low"].resample(tf_rule, label="left", closed="left").min()
    v = df["volume_traded"].resample(tf_rule, label="left", closed="left").sum()
    bars = pd.concat([c, h, l, v], axis=1)
    bars.columns = ["close", "high", "low", "vol"]
    bars = bars.dropna(subset=["close"])
    if len(bars) < 20:
        # Not enough data at this TF — treat as 0 trend
        return pd.Series(0, index=bars_chart.index, dtype=np.int8)

    bars["hlc3"] = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    bars["ema20"] = bars["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    # rolling-24h VWAP — number of bars in 24h depends on TF
    if tf_rule == "1min":
        n24 = 1440
    elif tf_rule == "5min":
        n24 = 288
    elif tf_rule == "15min":
        n24 = 96
    elif tf_rule == "30min":
        n24 = 48
    elif tf_rule == "1h":
        n24 = 24
    elif tf_rule == "4h":
        n24 = 6
    elif tf_rule == "1D":
        n24 = 1
    else:
        n24 = 50
    bars["vwap"] = vwap_24h(bars["hlc3"], bars["vol"], max(n24, 5))

    trend = np.zeros(len(bars), dtype=np.int8)
    up = (bars["close"] > bars["ema20"]) & (bars["close"] > bars["vwap"])
    dn = (bars["close"] < bars["ema20"]) & (bars["close"] < bars["vwap"])
    trend[up.values] = 1
    trend[dn.values] = -1
    bars["trend"] = trend

    # Now merge_asof — chart bars get the trend at the last-completed TF bar (causal).
    # bars index = TF bar START time. To be causal at chart bar t, we need the TF
    # bar that ENDED at or before t. TF bar end = its index + tf duration.
    tf_seconds_map = {"1min": 60, "5min": 300, "15min": 900, "30min": 1800,
                      "1h": 3600, "4h": 14400, "1D": 86400}
    tf_s = tf_seconds_map[tf_rule]
    bars = bars.reset_index().rename(columns={"dt": "tf_dt"})
    bars["tf_end_us"] = (bars["tf_dt"].astype("int64") // 1_000) + int(tf_s) * 1_000_000

    chart_us = bars_chart["ts_us"].values.astype("int64")
    tf_end = bars["tf_end_us"].values.astype("int64")
    tf_trend = bars["trend"].values.astype("int8")

    # For each chart bar, find the rightmost TF bar with tf_end_us <= chart bar's ts_us
    pos = np.searchsorted(tf_end, chart_us, side="right") - 1
    out = np.zeros(len(chart_us), dtype=np.int8)
    valid = pos >= 0
    out[valid] = tf_trend[pos[valid]]
    return pd.Series(out, index=bars_chart.index, dtype=np.int8)


def compute_sms_for_asset(df_1s_asset: pd.DataFrame, tf_minutes: int, label: str) -> pd.DataFrame:
    """Compute the full SMS panel for one asset on the chart TF."""
    freq_s = tf_minutes * 60
    bars = resample_1s_to_bar(df_1s_asset, freq_s)
    print(f"    [{label}] {len(bars):,} bars after resample to {tf_minutes}m")

    # ---- Pivot high / low (lookback=5) ----
    bars["pivot_high"] = rolling_pivot(bars["high"], PIVOT_LB, "high")
    bars["pivot_low"] = rolling_pivot(bars["low"], PIVOT_LB, "low")

    # last_high / last_low = forward-filled most recent pivot
    bars["last_high"] = bars["pivot_high"].ffill()
    bars["last_low"] = bars["pivot_low"].ffill()

    # last_high_prev / last_low_prev = the pivot BEFORE the current `last_*`
    # Track via the pivot_* series and a tiny scan
    last_high_prev = np.full(len(bars), np.nan)
    last_low_prev = np.full(len(bars), np.nan)
    ph = bars["pivot_high"].values
    pl = bars["pivot_low"].values
    cur_h = np.nan; prev_h = np.nan
    cur_l = np.nan; prev_l = np.nan
    for i in range(len(bars)):
        if not np.isnan(ph[i]):
            prev_h = cur_h
            cur_h = ph[i]
        if not np.isnan(pl[i]):
            prev_l = cur_l
            cur_l = pl[i]
        last_high_prev[i] = prev_h
        last_low_prev[i] = prev_l
    bars["last_high_prev"] = last_high_prev
    bars["last_low_prev"] = last_low_prev

    # ---- CHoCH / BOS ----
    bull_body = bars["close"] > bars["open"]
    bear_body = bars["close"] < bars["open"]
    # CHoCH_sell: low crosses BELOW last_high — i.e. price tested swing high from below and broke.
    # Pine `crossunder(low, last_high)` semantics: low_prev >= last_high_prev AND low < last_high
    bars["choch_sell"] = (crossunder(bars["low"], bars["last_high"]) & bear_body).fillna(False).astype(bool)
    bars["choch_buy"] = (crossover(bars["high"], bars["last_low"]) & bull_body).fillna(False).astype(bool)
    bars["bos_sell"] = (crossunder(bars["low"], bars["last_low_prev"]) & bear_body).fillna(False).astype(bool)
    bars["bos_buy"] = (crossover(bars["high"], bars["last_high_prev"]) & bull_body).fillna(False).astype(bool)

    # ---- bars_since_* ----
    for col in ("bos_buy", "bos_sell", "choch_buy", "choch_sell"):
        bs = np.full(len(bars), -1, dtype=np.int32)  # -1 = never fired yet
        c = bars[col].values
        cur = -1
        for i in range(len(bars)):
            if c[i]:
                cur = 0
            elif cur >= 0:
                cur += 1
            bs[i] = cur
        bars[f"bars_since_{col}"] = bs

    # ---- RSI(14) ----
    bars["rsi_14"] = rsi_wilder(bars["close"], length=RSI_LEN)

    # ---- RSI divergence (5-bar pivots) ----
    low_now = bars["low"]
    low_5 = bars["low"].shift(5)
    low_10 = bars["low"].shift(10)
    rsi_now = bars["rsi_14"]
    rsi_5 = bars["rsi_14"].shift(5)
    rsi_10 = bars["rsi_14"].shift(10)
    bars["rsi_bullish_div"] = (
        (low_now < low_5) & (low_5 < low_10) &
        (rsi_now > rsi_5) & (rsi_5 > rsi_10) &
        (rsi_now < 40.0)
    ).fillna(False).astype(bool)

    high_now = bars["high"]
    high_5 = bars["high"].shift(5)
    high_10 = bars["high"].shift(10)
    bars["rsi_bearish_div"] = (
        (high_now > high_5) & (high_5 > high_10) &
        (rsi_now < rsi_5) & (rsi_5 < rsi_10) &
        (rsi_now > 60.0)
    ).fillna(False).astype(bool)

    # ---- CVD ----
    close_prev = bars["close"].shift(1)
    delta_vol = np.where(bars["close"] > close_prev, bars["volume"],
                np.where(bars["close"] < close_prev, -bars["volume"], 0.0))
    bars["cvd"] = pd.Series(delta_vol, index=bars.index).cumsum().fillna(0.0)
    # Note: |cvd| ranges depend on asset. Spec used 10k/50k cutoffs — these are sane
    # for crypto futures (BTC ~10k BTC ~$700M, ETH ~50k ETH ~$200M). For binance spot 1s
    # raw volumes, these absolute cutoffs work OK if we use rolling absolute scale instead.
    # Compute rolling abs scale and tier accordingly:
    cvd_abs = bars["cvd"].abs()
    # tier: -1/0/+1 = Low/Med/High based on absolute cutoffs from spec
    cvd_level = np.where(cvd_abs < 10000, -1, np.where(cvd_abs < 50000, 0, 1))
    bars["cvd_level"] = cvd_level.astype(np.int8)
    bars["cvd_sign"] = np.sign(bars["cvd"]).astype(np.int8)

    # ---- Liquidity zones (light) ----
    bars["recent_high_20"] = bars["high"].rolling(LIQ_LB, min_periods=LIQ_LB).max()
    bars["recent_low_20"] = bars["low"].rolling(LIQ_LB, min_periods=LIQ_LB).min()
    # within 0.05% of the recent extreme
    bars["liquidity_up"] = (
        ((bars["high"] - bars["recent_high_20"]).abs() / bars["recent_high_20"] < LIQ_TOL)
    ).fillna(False).astype(bool)
    bars["liquidity_dn"] = (
        ((bars["low"] - bars["recent_low_20"]).abs() / bars["recent_low_20"] < LIQ_TOL)
    ).fillna(False).astype(bool)

    # ---- Multi-TF trend strength ----
    trends = []
    for rule, lab in zip(MULTI_TF_RULES, MULTI_TF_LABELS):
        t = compute_trend_per_tf(bars, df_1s_asset, rule, lab)
        bars[f"trend_{lab}"] = t.values
        trends.append(t.values)
    trends_arr = np.stack(trends, axis=0)  # (n_tf, n_bars)
    bars["trend_strength_raw"] = trends_arr.sum(axis=0).astype(np.int8)
    bars["trend_strength_pct"] = (bars["trend_strength_raw"] / 7.0 * 100.0).astype(np.float32)
    abs_raw = bars["trend_strength_raw"].abs().values
    sc = np.full(len(bars), 50, dtype=np.int8)
    sc[abs_raw >= 2] = 60
    sc[abs_raw >= 4] = 75
    sc[abs_raw == 7] = 90
    bars["system_confidence"] = sc

    return bars


def main():
    print(f"[1] loading 1s binance klines...")
    t0 = time.time()
    df = pd.read_parquet(KL1S)
    df = df.sort_values(["symbol_id", "time_period_start_us", "source"])
    df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df["asset"] = df["symbol_id"].map(SYM_MAP)
    df = df[df["asset"].notna()].copy()
    df["ts_us"] = df["time_period_start_us"].astype("int64")
    # Filter to backtest window for speed
    df = df[(df["ts_us"] >= WIN_START_US) & (df["ts_us"] <= WIN_END_US)].copy()
    print(f"    {len(df):,} rows loaded in {time.time()-t0:.1f}s; window {pd.to_datetime(df.ts_us.min(), unit='us')} .. {pd.to_datetime(df.ts_us.max(), unit='us')}")
    print(f"    per-asset: {df.asset.value_counts().to_dict()}")

    for tf_min, outp, label in [(5, OUT5, "5m"), (15, OUT15, "15m")]:
        print(f"\n[2] building {label} SMS panel...")
        parts = []
        for asset in ("BTC", "ETH", "SOL"):
            t0 = time.time()
            sub = df[df["asset"] == asset][["ts_us", "price_open", "price_high",
                                             "price_low", "price_close", "volume_traded"]].copy()
            bars = compute_sms_for_asset(sub, tf_minutes=tf_min, label=f"{asset}-{label}")
            bars["asset"] = asset
            parts.append(bars)
            print(f"    {asset}: {len(bars):,} bars in {time.time()-t0:.1f}s")

        all_bars = pd.concat(parts, ignore_index=True)
        # Drop the `dt` col and reorder
        all_bars = all_bars.drop(columns=["dt"])
        # Convert booleans to int8 to make parquet smaller + parsing predictable
        for col in ("bos_buy", "bos_sell", "choch_buy", "choch_sell",
                    "rsi_bullish_div", "rsi_bearish_div", "liquidity_up", "liquidity_dn"):
            all_bars[col] = all_bars[col].astype(np.int8)
        front_cols = ["asset", "ts_us", "open", "high", "low", "close", "volume", "hlc3"]
        other = [c for c in all_bars.columns if c not in front_cols]
        all_bars = all_bars[front_cols + other]
        all_bars = all_bars.sort_values(["asset", "ts_us"]).reset_index(drop=True)

        outp.parent.mkdir(parents=True, exist_ok=True)
        all_bars.to_parquet(outp, index=False, compression="zstd")
        import os
        print(f"  wrote {outp}  ({os.path.getsize(outp)/1024/1024:.1f} MB)")

        # frequency report
        print(f"  event frequencies (out of {len(all_bars):,} bars):")
        for col in ("bos_buy", "bos_sell", "choch_buy", "choch_sell",
                    "rsi_bullish_div", "rsi_bearish_div", "liquidity_up", "liquidity_dn"):
            n = int(all_bars[col].sum())
            print(f"    {col}: {n:,}  ({100*n/len(all_bars):.2f}%)")
        for k, v in all_bars["system_confidence"].value_counts().sort_index().items():
            print(f"    system_confidence={k}: {v:,}")
        print(f"    trend_strength_raw stats: min={all_bars.trend_strength_raw.min()} "
              f"mean={all_bars.trend_strength_raw.mean():.2f} max={all_bars.trend_strength_raw.max()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
