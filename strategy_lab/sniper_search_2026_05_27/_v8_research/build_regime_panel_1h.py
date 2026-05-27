"""V8 — Build 1h regime panel as Path L grandparent layer.

Mirrors `meta_classifier/build_regime_panel.py` but for the 1h grid.
- 1m bars from klines_1m (BINANCE_SPOT 1MIN) → aggregate to 1h
- ADX(14) Wilder on 1h
- EMA stack score on 1h (close vs ema50/ema200)
- realized_vol_60m: from 1m logreturns rolling 60-min stdev, as-of bar end
- trend_slope_30m: same approach
- regime_label: trending_up / trending_dn / ranging based on adx_14 + ema_stack + ribbon
  (ribbon may be NaN outside ta panel coverage — fallback uses adx + stack only)

Output: data/v4/canonical/_results/regime_panel_1h.parquet
        Columns: asset, tf=1h, ts_us (bar END), ts_s, open, high, low, close, volume,
                 adx_14, plus_di_14, minus_di_14, atr_14,
                 tr_ema_stack_score, ribbon_alignment_pct, bb_width_60s,
                 realized_vol_60m, range_compression, trend_slope_30m,
                 regime_label, regime_score
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_PATH = OUT_DIR / "regime_panel_1h.parquet"

# Cover the v3 fires window with some warmup
WIN_START_US = int(dt.datetime(2026, 4, 22, tzinfo=dt.timezone.utc).timestamp() * 1e6)
WIN_END_US   = int(dt.datetime(2026, 5, 26, 18, tzinfo=dt.timezone.utc).timestamp() * 1e6)

KLINES_1M = ROOT / "data" / "v4" / "canonical" / "klines_1m.parquet"
TA_PANEL  = ROOT / "data" / "v4" / "canonical" / "_results" / "ta_indicators_1s.parquet"


# ------------------------------------------------------------------
# Wilder ADX (vendored from build_regime_panel.py to keep self-contained)
# ------------------------------------------------------------------

def wilder_smooth(arr: np.ndarray, period: int) -> np.ndarray:
    n = arr.shape[0]
    out = np.full(n, np.nan)
    if n < period: return out
    avg = float(np.nanmean(arr[:period]))
    out[period - 1] = avg
    for i in range(period, n):
        x = arr[i]
        if not np.isfinite(x): x = 0.0
        avg = (avg * (period - 1) + x) / period
        out[i] = avg
    return out


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    h = out["high"].values.astype(float)
    l = out["low"].values.astype(float)
    c = out["close"].values.astype(float)
    n = len(out)
    if n < period * 3:
        out[f"adx_{period}"] = np.nan
        out[f"plus_di_{period}"] = np.nan
        out[f"minus_di_{period}"] = np.nan
        out[f"atr_{period}"] = np.nan
        return out
    tr  = np.zeros(n); pdm = np.zeros(n); ndm = np.zeros(n)
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
    out[f"atr_{period}"]      = sm_tr
    return out


# ------------------------------------------------------------------
# Main pipeline
# ------------------------------------------------------------------

SYMBOL_MAP = {
    "BTC": "BINANCE_SPOT_BTC_USDT",
    "ETH": "BINANCE_SPOT_ETH_USDT",
    "SOL": "BINANCE_SPOT_SOL_USDT",
}


def get_1m_bars(asset: str) -> pd.DataFrame:
    """Return 1MIN bars for asset within window (with prefix warmup)."""
    sym = SYMBOL_MAP[asset]
    df = pd.read_parquet(KLINES_1M, columns=[
        "symbol_id", "period_id", "time_period_start_us", "time_period_end_us",
        "price_open", "price_high", "price_low", "price_close", "volume_traded",
    ])
    df = df[(df.symbol_id == sym) & (df.period_id == "1MIN")]
    df = df.rename(columns={
        "time_period_start_us": "ts_us",
        "price_open": "open", "price_high": "high",
        "price_low": "low",  "price_close": "close",
        "volume_traded": "volume",
    })[["ts_us", "open", "high", "low", "close", "volume"]]
    # Need warmup of ~250h for ema200_1h => 250*60 = 15,000 1m bars => add 11 day buffer
    df = df[(df.ts_us >= WIN_START_US - 11 * 86_400_000_000) & (df.ts_us < WIN_END_US)]
    df = df.sort_values("ts_us").drop_duplicates("ts_us", keep="first").reset_index(drop=True)
    return df


def resample_to_1h(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m → 1h. ts_us = bar END (slot_start + 1h - 1us) for causal asof."""
    out = df_1m.copy()
    bar_us = 3600 * 1_000_000
    out["slot_us"] = (out["ts_us"] // bar_us) * bar_us
    agg = out.groupby("slot_us").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    agg["slot_start_us"] = agg["slot_us"]
    agg["ts_us"] = agg["slot_us"] + bar_us - 1
    agg = agg.drop(columns=["slot_us"])
    agg["ts_s"] = agg["ts_us"] // 1_000_000
    return agg


def compute_vol_features_1h(df: pd.DataFrame) -> pd.DataFrame:
    """1h-scale vol features: 60-bar = 60-hour rolling.

    For grandparent context we want SLOWER vol features:
      - realized_vol_60h: stdev of 60 1h log returns
      - range_compression: (high_60h - low_60h) / atr_60h
      - trend_slope_30h: (close - close_30h_ago) / atr_60h
    """
    out = df.copy()
    c = out["close"].astype(float)
    out["logret_1h"] = np.log(c).diff()
    out["realized_vol_60m"] = out["logret_1h"].rolling(60, min_periods=20).std()  # 60h vol
    out["high_60m"] = out["high"].rolling(60, min_periods=20).max()
    out["low_60m"]  = out["low"].rolling(60, min_periods=20).min()
    h = out["high"].values; l = out["low"].values; c_arr = out["close"].values
    n = len(out)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c_arr[i - 1]), abs(l[i] - c_arr[i - 1]))
    out["tr_1h"] = tr
    out["atr_60m"] = pd.Series(tr).rolling(60, min_periods=20).mean()
    out["range_compression"] = (out["high_60m"] - out["low_60m"]) / out["atr_60m"]
    out["close_30h_ago"] = c.shift(30)
    out["trend_slope_30m"] = (c - out["close_30h_ago"]) / out["atr_60m"]
    return out


def compute_tr_ema_stack_1h(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"].astype(float)
    ema50  = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    bull2 = (c > ema50) & (ema50 > ema200)
    bear2 = (c < ema50) & (ema50 < ema200)
    bull1 = (c > ema50) & ~bull2
    bear1 = (c < ema50) & ~bear2
    score = np.where(bull2, 2,
            np.where(bull1, 1,
            np.where(bear2, -2,
            np.where(bear1, -1, 0))))
    out["tr_ema_stack_score"] = score.astype(float)
    return out


def compute_regime_label_and_score(df: pd.DataFrame) -> pd.DataFrame:
    """3-state regime classifier mirroring 5m/15m v2_fixed semantics.

    For 1h grandparent, we relax the ribbon constraint:
      trending_up: adx_14 > 20 AND tr_ema_stack_score >= +1 AND (ribbon_alignment_pct >= 60 OR ribbon is NaN)
      trending_dn: adx_14 > 20 AND tr_ema_stack_score <= -1 AND (ribbon_alignment_pct >= 60 OR ribbon is NaN)
      ranging:     else

    Lower adx threshold (20 vs 25) and relaxed ribbon to acknowledge that 1h trends are
    slower to confirm and ribbon (computed on 1s data) may be missing outside TA panel
    coverage.
    """
    out = df.copy()
    adx = out["adx_14"].astype(float)
    stack = out["tr_ema_stack_score"].astype(float)
    if "ribbon_alignment_pct" not in out.columns:
        out["ribbon_alignment_pct"] = np.nan
    ribbon = out["ribbon_alignment_pct"]

    ribbon_ok = (ribbon.isna()) | (ribbon >= 60)

    label = pd.Series("ranging", index=out.index)
    label[(adx > 20) & (stack >= 1) & ribbon_ok] = "trending_up"
    label[(adx > 20) & (stack <= -1) & ribbon_ok] = "trending_dn"
    out["regime_label"] = label

    direction = np.tanh(stack / 2.0)
    strength = (np.minimum(adx, 50.0) / 50.0)
    out["regime_score"] = direction * strength
    return out


def build_for_asset(asset: str, ta_panel_path: Path | None) -> pd.DataFrame:
    print(f"[{asset}] loading 1m bars", flush=True)
    bars_1m = get_1m_bars(asset)
    print(f"[{asset}] 1m bars: {len(bars_1m):,}", flush=True)

    # 1h grid
    bars_1h = resample_to_1h(bars_1m)
    print(f"[{asset}] 1h bars: {len(bars_1h):,}", flush=True)

    bars_1h = compute_adx(bars_1h, 14)
    bars_1h = compute_tr_ema_stack_1h(bars_1h)
    bars_1h = compute_vol_features_1h(bars_1h)

    # Try to merge TA panel ribbon_alignment_pct (best-effort; will be NaN outside coverage)
    if ta_panel_path and ta_panel_path.exists():
        try:
            ta = pd.read_parquet(ta_panel_path, columns=[
                "asset", "ts_us", "ribbon_alignment_pct", "bb_width_60s",
            ])
            ta = ta[ta.asset == asset].sort_values("ts_us")
            bars_1h = bars_1h.sort_values("ts_us")
            bars_1h["bar_end_us"] = bars_1h["ts_us"]
            merged = pd.merge_asof(
                bars_1h, ta[["ts_us", "ribbon_alignment_pct", "bb_width_60s"]],
                left_on="bar_end_us", right_on="ts_us",
                direction="backward",
                tolerance=120_000_000,
                suffixes=("", "_ta"),
            )
            merged = merged.drop(columns=["ts_us_ta"], errors="ignore")
            bars_1h = merged.sort_values("ts_us").reset_index(drop=True)
        except Exception as e:
            print(f"  TA merge fail {asset}: {e}", flush=True)
            bars_1h["ribbon_alignment_pct"] = np.nan
            bars_1h["bb_width_60s"] = np.nan
    else:
        bars_1h["ribbon_alignment_pct"] = np.nan
        bars_1h["bb_width_60s"] = np.nan

    bars_1h = compute_regime_label_and_score(bars_1h)
    bars_1h["asset"] = asset
    bars_1h["tf"] = "1h"
    return bars_1h


def main():
    OUT_DIR.mkdir(exist_ok=True, parents=True)
    all_1h = []
    for asset in ["BTC", "ETH", "SOL"]:
        b1h = build_for_asset(asset, TA_PANEL)
        b1h = b1h[(b1h.ts_us >= WIN_START_US) & (b1h.ts_us < WIN_END_US)]
        print(f"[{asset}] 1h window rows: {len(b1h):,}", flush=True)
        all_1h.append(b1h)

    panel_1h = pd.concat(all_1h, ignore_index=True)
    keep_cols = ["asset", "tf", "ts_us", "ts_s", "open", "high", "low", "close", "volume",
                 "adx_14", "plus_di_14", "minus_di_14", "atr_14",
                 "tr_ema_stack_score", "ribbon_alignment_pct", "bb_width_60s",
                 "realized_vol_60m", "range_compression", "trend_slope_30m",
                 "regime_label", "regime_score"]
    panel_1h = panel_1h[[c for c in keep_cols if c in panel_1h.columns]]
    panel_1h.to_parquet(OUT_PATH, compression="snappy", index=False)
    print(f"wrote: {OUT_PATH}", flush=True)
    print()
    print("=== 1h regime_label distribution (window-filtered) ===")
    print(panel_1h.groupby(["asset", "regime_label"]).size().unstack(fill_value=0))
    print()
    print("=== adx_14 quantiles ===")
    print(panel_1h.groupby("asset")["adx_14"].describe(percentiles=[.25,.5,.75,.9]))


if __name__ == "__main__":
    main()
