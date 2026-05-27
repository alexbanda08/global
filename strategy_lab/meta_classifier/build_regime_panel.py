"""Regime panel builder — 3-state classifier (trending_up/trending_dn/ranging).

Builds per-asset, per-bar regime features on 5m and 15m grids from binance-vision
1MIN klines + 1s aggregated. Computes:

  - adx_14            ADX(14) Wilder smoothing
  - realized_vol_60m  stdev of 1-minute log returns over last 60 min
  - range_compression (high_60m - low_60m) / atr_60m
  - trend_slope_30m   slope of close over last 30m / atr_60m
  - ribbon_alignment_pct  (from ta_indicators_1s panel, asof at bar end)
  - tr_ema_stack_score    (recomputed here on bar-grid)
  - bb_width_60s          (from ta panel)

  regime_label:
    trending_up : adx_14 > 25 AND tr_ema_stack_score >= +1 AND ribbon_alignment_pct >= 70
    trending_dn : adx_14 > 25 AND tr_ema_stack_score <= -1 AND ribbon_alignment_pct >= 70
    ranging     : else

  regime_score: continuous (-1..+1)
    direction = tanh(tr_ema_stack_score / 2)  in (-1,+1)
    strength  = min(adx_14 / 50, 1) * min(ribbon_alignment_pct / 100, 1)
    regime_score = direction * strength

Output:
  data/v4/canonical/_results/regime_panel_5m.parquet
  data/v4/canonical/_results/regime_panel_15m.parquet
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_klines_1s, load_binance_vision_klines  # noqa: E402

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"

# Window: 2026-04-28 → 2026-05-25 (covers Apr 30 → May 22 backtest with buffer)
WIN_START_US = int(dt.datetime(2026, 4, 28, tzinfo=dt.timezone.utc).timestamp() * 1e6)
WIN_END_US   = int(dt.datetime(2026, 5, 26, tzinfo=dt.timezone.utc).timestamp() * 1e6)


# ----------------------------------------------------------------------------
# 1MIN bar source: combine vision (Apr 7 - Apr 28) + aggregate from 1s (Apr 7 - May 25)
# Per-asset.
# ----------------------------------------------------------------------------

def get_1m_bars(asset: str) -> pd.DataFrame:
    """Return columns: ts_s (start), open, high, low, close, volume. Sorted ascending."""
    parts = []
    # Vision 1MIN, full window
    try:
        v = load_binance_vision_klines(asset, "1MIN")
        if len(v):
            v = v.rename(columns={
                "time_period_start_us": "ts_us",
                "price_open": "open", "price_high": "high",
                "price_low": "low", "price_close": "close",
                "volume_traded": "volume",
            })[["ts_us", "open", "high", "low", "close", "volume"]]
            v = v[(v.ts_us >= WIN_START_US - 86_400_000_000) & (v.ts_us < WIN_END_US)]
            parts.append(v)
    except Exception as e:
        print(f"  vision load fail {asset}: {e}")

    # Aggregate 1s -> 1m for ws-spot coverage (May 7+)
    ks = load_klines_1s(asset)
    if len(ks):
        ks = ks.rename(columns={
            "time_period_start_us": "ts_us",
            "price_open": "open", "price_high": "high",
            "price_low": "low", "price_close": "close",
            "volume_traded": "volume",
        })[["ts_us", "open", "high", "low", "close", "volume"]]
        ks = ks[(ks.ts_us >= WIN_START_US - 86_400_000_000) & (ks.ts_us < WIN_END_US)]
        ks["minute_us"] = (ks.ts_us // 60_000_000) * 60_000_000
        agg = ks.groupby("minute_us").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).reset_index().rename(columns={"minute_us": "ts_us"})
        parts.append(agg)

    if not parts:
        raise RuntimeError(f"no 1m bars for {asset}")
    df = pd.concat(parts, ignore_index=True)
    # de-dup, prefer vision when overlap (vision is canonical archive). agg comes second,
    # so drop_duplicates keep='first' favors vision.
    df = df.sort_values("ts_us").drop_duplicates("ts_us", keep="first").reset_index(drop=True)
    df["ts_s"] = df.ts_us // 1_000_000
    return df


# ----------------------------------------------------------------------------
# ADX(14) Wilder smoothing
# ----------------------------------------------------------------------------

def wilder_smooth(arr: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing producing the AVERAGED value (not the sum).
      avg[period-1] = mean(arr[0:period])
      avg[i]        = (avg[i-1] * (period - 1) + arr[i]) / period   for i >= period
    Returns array same shape, NaN for first period-1 indices.
    """
    n = arr.shape[0]
    out = np.full(n, np.nan)
    if n < period:
        return out
    avg = float(np.nanmean(arr[:period]))
    out[period - 1] = avg
    for i in range(period, n):
        x = arr[i]
        if not np.isfinite(x):
            x = 0.0
        avg = (avg * (period - 1) + x) / period
        out[i] = avg
    return out


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add adx_{period}, plus_di_{period}, minus_di_{period} columns.
    Standard Wilder's method:
      TR = max(H-L, |H-prevC|, |L-prevC|)
      +DM = max(H - prevH, 0) if H-prevH > prevL-L else 0
      -DM = max(prevL - L, 0) if prevL-L > H-prevH else 0
      Smoothed via Wilder over `period`.
      +DI = 100 * smoothed_+DM / smoothed_TR
      -DI = 100 * smoothed_-DM / smoothed_TR
      DX  = 100 * |+DI - -DI| / (+DI + -DI)
      ADX = Wilder smoothed DX (period)
    """
    out = df.copy()
    h = out["high"].values.astype(float)
    l = out["low"].values.astype(float)
    c = out["close"].values.astype(float)
    n = len(out)
    if n < period * 3:
        out[f"adx_{period}"] = np.nan
        out[f"plus_di_{period}"] = np.nan
        out[f"minus_di_{period}"] = np.nan
        return out

    tr  = np.zeros(n)
    pdm = np.zeros(n)
    ndm = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        up_move = h[i] - h[i - 1]
        dn_move = l[i - 1] - l[i]
        pdm[i] = up_move if (up_move > dn_move and up_move > 0) else 0.0
        ndm[i] = dn_move if (dn_move > up_move and dn_move > 0) else 0.0
        tr[i]  = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    sm_tr  = wilder_smooth(tr, period)
    sm_pdm = wilder_smooth(pdm, period)
    sm_ndm = wilder_smooth(ndm, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100.0 * sm_pdm / sm_tr
        ndi = 100.0 * sm_ndm / sm_tr
        denom = pdi + ndi
        dx = np.where(denom > 0, 100.0 * np.abs(pdi - ndi) / denom, 0.0)
    adx = wilder_smooth(dx, period)

    out[f"adx_{period}"]      = adx
    out[f"plus_di_{period}"]  = pdi
    out[f"minus_di_{period}"] = ndi
    out[f"atr_{period}"]      = sm_tr   # already an average per wilder_smooth
    return out


# ----------------------------------------------------------------------------
# Tr_ema_stack_score on bar grid (mirrors TA panel definition)
# Trader's Reality EMA stack: positive = stack(close > ema50 > ema200), bearish opposite.
# Score range -2..+2:
#   +2: close > ema50 > ema200 (full bull stack)
#   +1: close > ema50 but ema50 <= ema200 (partial bull)
#    0: mixed / undefined
#   -1: close < ema50 but ema50 >= ema200 (partial bear)
#   -2: close < ema50 < ema200 (full bear stack)
# ----------------------------------------------------------------------------

def compute_tr_ema_stack(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"].astype(float)
    # EMAs (period in bars; bars here are 1m)
    ema50  = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    out["bar_ema_50"]  = ema50
    out["bar_ema_200"] = ema200
    bull2 = (c > ema50) & (ema50 > ema200)
    bear2 = (c < ema50) & (ema50 < ema200)
    bull1 = (c > ema50) & ~bull2
    bear1 = (c < ema50) & ~bear2
    score = np.where(bull2,  2,
            np.where(bull1,  1,
            np.where(bear2, -2,
            np.where(bear1, -1, 0))))
    out["tr_ema_stack_score_1m"] = score.astype(float)
    return out


# ----------------------------------------------------------------------------
# Realized vol, range compression, trend slope
# ----------------------------------------------------------------------------

def compute_vol_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"].astype(float)
    # 1-min log returns
    out["logret_1m"] = np.log(c).diff()
    # realized_vol_60m: stdev of last 60 1m log returns (rolling)
    out["realized_vol_60m"] = out["logret_1m"].rolling(60, min_periods=30).std()
    # 60m high/low
    out["high_60m"] = out["high"].rolling(60, min_periods=30).max()
    out["low_60m"]  = out["low"].rolling(60, min_periods=30).min()
    # ATR(60m). Reuse 1m TR and average over 60.
    h = out["high"].values
    l = out["low"].values
    c_arr = out["close"].values
    n = len(out)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c_arr[i - 1]), abs(l[i] - c_arr[i - 1]))
    out["tr_1m"] = tr
    out["atr_60m"] = pd.Series(tr).rolling(60, min_periods=30).mean()
    out["range_compression"] = (out["high_60m"] - out["low_60m"]) / out["atr_60m"]
    # trend slope over last 30m, normalized by ATR(60m)
    # slope = (close - close_30m_ago) / atr_60m
    out["close_30m_ago"] = c.shift(30)
    out["trend_slope_30m"] = (c - out["close_30m_ago"]) / out["atr_60m"]
    return out


# ----------------------------------------------------------------------------
# Asof-join TA panel features (ribbon_alignment_pct, bb_width_60s)
# TA panel is 1s-grid; we asof to 1m bar END (ts_us + 60_000_000 - 1).
# ----------------------------------------------------------------------------

def asof_ta_panel(bars_1m: pd.DataFrame, ta_panel: pd.DataFrame) -> pd.DataFrame:
    """Merge ribbon_alignment_pct, bb_width_60s, tr_ema_stack_score (from TA panel
    if present), as-of bar END."""
    out = bars_1m.copy()
    out["bar_end_us"] = out["ts_us"] + 60_000_000 - 1
    ta = ta_panel.sort_values("ts_us")[["ts_us", "ribbon_alignment_pct", "bb_width_60s"]]
    out = out.sort_values("bar_end_us")
    merged = pd.merge_asof(
        out, ta,
        left_on="bar_end_us", right_on="ts_us",
        direction="backward",
        tolerance=5_000_000,   # 5s tolerance
        suffixes=("", "_ta"),
    )
    merged = merged.drop(columns=["ts_us_ta"]).sort_values("ts_us")
    return merged.reset_index(drop=True)


# ----------------------------------------------------------------------------
# Resample 1m -> 5m / 15m bars + recompute regime features on those grids.
# ----------------------------------------------------------------------------

def resample_to_bar(df_1m: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Resample 1m bars to N-minute bars.

    AUDIT-FIX 2026-05-26 (Bug #2): ts_us is now BAR END (slot_start + tf_seconds - 1us).
    Previously ts_us = bar START, which caused a merge_asof leak: backward-asof joins
    on fire_us would pick the bar whose features were computed over the FUTURE
    (0-300s past fire_us). 19.5% of BTC 5m fires got a different regime_label than
    the causal prior bar. Now keying at bar END makes merge_asof(direction='backward')
    strictly causal — it picks the latest CLOSED bar.
    """
    out = df_1m.copy()
    out["slot_us"] = (out["ts_us"] // (minutes * 60_000_000)) * (minutes * 60_000_000)
    agg = out.groupby("slot_us").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    # FIX: rekey at bar END so merge_asof backward is strictly causal
    bar_us = minutes * 60_000_000
    agg["slot_start_us"] = agg["slot_us"]
    agg["ts_us"] = agg["slot_us"] + bar_us - 1  # bar END (inclusive last microsecond)
    agg = agg.drop(columns=["slot_us"])
    agg["ts_s"] = agg.ts_us // 1_000_000
    return agg


def compute_regime_label_and_score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    adx = out["adx_14"].astype(float)
    stack = out["tr_ema_stack_score"].astype(float)
    ribbon = out["ribbon_alignment_pct"].astype(float)

    # default ranging
    label = pd.Series("ranging", index=out.index)
    label[(adx > 25) & (stack >= 1) & (ribbon >= 70)] = "trending_up"
    label[(adx > 25) & (stack <= -1) & (ribbon >= 70)] = "trending_dn"
    out["regime_label"] = label

    # continuous regime score (-1 .. +1)
    direction = np.tanh(stack / 2.0)
    strength = (np.minimum(adx, 50.0) / 50.0) * (np.minimum(ribbon, 100.0) / 100.0)
    out["regime_score"] = direction * strength
    return out


# ----------------------------------------------------------------------------
# Main per-asset pipeline
# ----------------------------------------------------------------------------

def build_for_asset(asset: str, ta_panel_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    print(f"[{asset}] loading 1m bars")
    bars_1m = get_1m_bars(asset)
    print(f"[{asset}] 1m bars: {len(bars_1m):,}")

    print(f"[{asset}] loading TA panel (filtered to {asset})")
    ta = pd.read_parquet(ta_panel_path, columns=["asset", "ts_us", "ribbon_alignment_pct", "bb_width_60s"])
    ta = ta[ta.asset == asset]
    print(f"[{asset}] TA panel rows for asset: {len(ta):,}")

    # 1m features
    bars_1m = compute_adx(bars_1m, 14)
    bars_1m = compute_tr_ema_stack(bars_1m)
    bars_1m = compute_vol_features(bars_1m)
    bars_1m = asof_ta_panel(bars_1m, ta)

    # 5m grid
    bars_5m = resample_to_bar(bars_1m, 5)
    bars_5m = compute_adx(bars_5m, 14)
    # tr_ema_stack on 5m grid uses ema50 + ema200 on 5m
    c = bars_5m["close"].astype(float)
    ema50_5  = c.ewm(span=50, adjust=False).mean()
    ema200_5 = c.ewm(span=200, adjust=False).mean()
    bull2 = (c > ema50_5) & (ema50_5 > ema200_5)
    bear2 = (c < ema50_5) & (ema50_5 < ema200_5)
    bull1 = (c > ema50_5) & ~bull2
    bear1 = (c < ema50_5) & ~bear2
    score5 = np.where(bull2, 2, np.where(bull1, 1, np.where(bear2, -2, np.where(bear1, -1, 0))))
    bars_5m["tr_ema_stack_score"] = score5.astype(float)
    # AUDIT-FIX 2026-05-26: ts_us is already bar END after resample_to_bar fix
    # bar_end_us keeps the same value (= ts_us) for back-compat with downstream
    bars_5m["bar_end_us"] = bars_5m["ts_us"]
    # Use 1m's realized_vol_60m at-or-before bar end + ribbon/bb_width
    asof_1m = bars_1m[["ts_us", "realized_vol_60m", "ribbon_alignment_pct", "bb_width_60s",
                       "range_compression", "trend_slope_30m"]].sort_values("ts_us")
    bars_5m = bars_5m.sort_values("bar_end_us")
    bars_5m = pd.merge_asof(
        bars_5m, asof_1m,
        left_on="bar_end_us", right_on="ts_us",
        direction="backward",
        tolerance=120_000_000,   # 2 min tolerance (1m bar starts up to 60s before bar_end)
        suffixes=("", "_1m"),
    ).drop(columns=["ts_us_1m"]).sort_values("ts_us").reset_index(drop=True)
    bars_5m = compute_regime_label_and_score(bars_5m)
    bars_5m["asset"] = asset
    bars_5m["tf"] = "5m"

    # 15m grid
    bars_15m = resample_to_bar(bars_1m, 15)
    bars_15m = compute_adx(bars_15m, 14)
    c = bars_15m["close"].astype(float)
    ema50_15  = c.ewm(span=50, adjust=False).mean()
    ema200_15 = c.ewm(span=200, adjust=False).mean()
    bull2 = (c > ema50_15) & (ema50_15 > ema200_15)
    bear2 = (c < ema50_15) & (ema50_15 < ema200_15)
    bull1 = (c > ema50_15) & ~bull2
    bear1 = (c < ema50_15) & ~bear2
    score15 = np.where(bull2, 2, np.where(bull1, 1, np.where(bear2, -2, np.where(bear1, -1, 0))))
    bars_15m["tr_ema_stack_score"] = score15.astype(float)
    # AUDIT-FIX 2026-05-26: ts_us is already bar END after resample_to_bar fix
    bars_15m["bar_end_us"] = bars_15m["ts_us"]
    bars_15m = bars_15m.sort_values("bar_end_us")
    bars_15m = pd.merge_asof(
        bars_15m, asof_1m,
        left_on="bar_end_us", right_on="ts_us",
        direction="backward",
        tolerance=120_000_000,
        suffixes=("", "_1m"),
    ).drop(columns=["ts_us_1m"]).sort_values("ts_us").reset_index(drop=True)
    bars_15m = compute_regime_label_and_score(bars_15m)
    bars_15m["asset"] = asset
    bars_15m["tf"] = "15m"

    return bars_5m, bars_15m


def main():
    OUT_DIR.mkdir(exist_ok=True, parents=True)
    ta_panel_path = ROOT / "data" / "v4" / "canonical" / "_results" / "ta_indicators_1s.parquet"
    if not ta_panel_path.exists():
        print(f"ERROR: missing {ta_panel_path}")
        sys.exit(1)

    all_5m = []
    all_15m = []
    for asset in ["BTC", "ETH", "SOL"]:
        b5, b15 = build_for_asset(asset, ta_panel_path)
        # Filter to window
        b5  = b5 [(b5.ts_us  >= WIN_START_US) & (b5.ts_us  < WIN_END_US)]
        b15 = b15[(b15.ts_us >= WIN_START_US) & (b15.ts_us < WIN_END_US)]
        print(f"[{asset}] 5m window rows: {len(b5):,}, 15m: {len(b15):,}")
        all_5m.append(b5)
        all_15m.append(b15)

    panel_5m  = pd.concat(all_5m, ignore_index=True)
    panel_15m = pd.concat(all_15m, ignore_index=True)

    # Pick canonical columns
    keep_cols = ["asset", "tf", "ts_us", "ts_s", "open", "high", "low", "close", "volume",
                 "adx_14", "plus_di_14", "minus_di_14", "atr_14",
                 "tr_ema_stack_score", "ribbon_alignment_pct", "bb_width_60s",
                 "realized_vol_60m", "range_compression", "trend_slope_30m",
                 "regime_label", "regime_score"]
    panel_5m  = panel_5m [[c for c in keep_cols if c in panel_5m.columns]]
    panel_15m = panel_15m[[c for c in keep_cols if c in panel_15m.columns]]

    out5  = OUT_DIR / "regime_panel_5m.parquet"
    out15 = OUT_DIR / "regime_panel_15m.parquet"
    panel_5m.to_parquet(out5,  compression="snappy", index=False)
    panel_15m.to_parquet(out15, compression="snappy", index=False)
    print("wrote:", out5)
    print("wrote:", out15)
    print()
    print("=== 5m label distribution (window-filtered) ===")
    print(panel_5m.groupby(["asset", "regime_label"]).size().unstack(fill_value=0))
    print()
    print("=== 15m label distribution ===")
    print(panel_15m.groupby(["asset", "regime_label"]).size().unstack(fill_value=0))
    print()
    print("=== regime_score quantiles 5m ===")
    print(panel_5m.groupby("asset")["regime_score"].describe(percentiles=[.1,.25,.5,.75,.9]))


if __name__ == "__main__":
    main()
