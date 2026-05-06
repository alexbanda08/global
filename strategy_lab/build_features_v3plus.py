"""
build_features_v3plus — extend btc_features_v3.csv with the 6 regime features
that earned a top-15 importance slot in the meta-classifier ablation.

Inputs:
  strategy_lab/data/polymarket/btc_features_v3.csv          (32 cols, 2,734 rows)
  strategy_lab/kronos_ft/data/BTCUSDT_5m_ext.csv            (BTC 5m OHLCV)
  data/v4/derivatives_zscore/panels/BTCUSDT_zscore.parquet  (z-score panel)

Output:
  strategy_lab/data/polymarket/btc_features_v3plus.csv      (38 cols, 2,734 rows)

Added columns (snapshot at ctx_end = window_start - 5min):
  btc_dist_ma200_5m  -- price_vs_ma200_pct (continuous)        [BTC 5m]
  btc_adx_14_5m      -- adx_14 (continuous)                    [BTC 5m]
  btc_z_oi_silent    -- z_oi_silent                            [deriv panel]
  btc_z_top_lsr_sum  -- z_top_lsr_sum                          [deriv panel]
  btc_z_taker_ratio  -- z_taker_ratio                          [deriv panel]
  btc_z_oi           -- z_oi                                   [deriv panel]

Helper functions copied verbatim from
strategy_lab/meta_classifier/build_dataset.py to keep computation identical.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PM = ROOT / "strategy_lab" / "data" / "polymarket"
V3_CSV = PM / "btc_features_v3.csv"
BTC_5M = ROOT / "strategy_lab" / "kronos_ft" / "data" / "BTCUSDT_5m_ext.csv"
DERIV_PANEL = ROOT / "data" / "v4" / "derivatives_zscore" / "panels" / "BTCUSDT_zscore.parquet"
OUT_CSV = PM / "btc_features_v3plus.csv"

ATR_PERIOD = 14
MA200_PERIOD = 200       # 200 bars on 5m = ~16.7h


def wilder_smooth(s: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing — equivalent to EMA with alpha=1/n, min_periods=n."""
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def add_atr_adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = wilder_smooth(tr, n)

    up_move = high - prev_high
    dn_move = prev_low - low
    plus_dm = ((up_move > dn_move) & (up_move > 0)).astype(float) * up_move
    minus_dm = ((dn_move > up_move) & (dn_move > 0)).astype(float) * dn_move

    plus_dm_s = wilder_smooth(plus_dm, n)
    minus_dm_s = wilder_smooth(minus_dm, n)
    tr_s = wilder_smooth(tr, n)

    plus_di = 100.0 * plus_dm_s / tr_s.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_s / tr_s.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = wilder_smooth(dx, n)

    df["atr_14"] = atr
    df["atr_pct"] = atr / close
    df["adx_14"] = adx
    df["plus_di_14"] = plus_di
    df["minus_di_14"] = minus_di
    return df


def add_price_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """MA-based regime features computed on the 5m series."""
    close = df["close"]
    ma200 = close.rolling(MA200_PERIOD, min_periods=MA200_PERIOD).mean()
    df["ma200"] = ma200
    df["price_vs_ma200_pct"] = (close - ma200) / ma200
    return df


def main():
    print("=== build_features_v3plus ===")

    # 1. Load V3 features (input)
    print(f"[1] loading V3 features: {V3_CSV}")
    v3 = pd.read_csv(V3_CSV)
    n_in = len(v3)
    n_cols_in = len(v3.columns)
    print(f"  rows: {n_in}, cols: {n_cols_in}")

    # 2. Compute ctx_end timestamps from window_start_unix (= window_start - 5min)
    #    - ctx_end_cest: tz-naive Berlin time (matches BTC 5m parquet snapshot key)
    #    - ctx_end_utc:  tz-aware UTC (matches deriv panel index)
    ws_utc = pd.to_datetime(v3["window_start_unix"], unit="s", utc=True)
    ctx_end_utc = ws_utc - pd.Timedelta(minutes=5)
    ctx_end_cest = (ws_utc.dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
                    - pd.Timedelta(minutes=5))

    # 3. BTC 5m TA + price regime features
    print(f"[2] computing ATR/ADX + MA200 from {BTC_5M}")
    btc = pd.read_csv(BTC_5M)
    btc["timestamps"] = pd.to_datetime(btc["timestamps"])
    btc = btc.sort_values("timestamps").reset_index(drop=True)
    btc = add_atr_adx(btc, n=ATR_PERIOD)
    btc = add_price_regime_features(btc)
    print(f"  5m bars: {len(btc):,}  range: {btc['timestamps'].min()} -> {btc['timestamps'].max()}")

    btc_idx = btc.set_index("timestamps")
    snap_5m = btc_idx[["price_vs_ma200_pct", "adx_14"]].reindex(ctx_end_cest).reset_index(drop=True)
    snap_5m = snap_5m.rename(columns={
        "price_vs_ma200_pct": "btc_dist_ma200_5m",
        "adx_14": "btc_adx_14_5m",
    })
    print(f"  TA snapshot non-null: dist_ma200={snap_5m['btc_dist_ma200_5m'].notna().sum()}, adx_14={snap_5m['btc_adx_14_5m'].notna().sum()}")

    # 4. Deriv z-score panel snapshot at ctx_end_utc
    print(f"[3] loading deriv z-score panel: {DERIV_PANEL}")
    deriv = pd.read_parquet(DERIV_PANEL)
    deriv_cols = ["z_oi_silent", "z_top_lsr_sum", "z_taker_ratio", "z_oi"]
    snap_dz = deriv[deriv_cols].reindex(ctx_end_utc).reset_index(drop=True)
    snap_dz = snap_dz.rename(columns={
        "z_oi_silent": "btc_z_oi_silent",
        "z_top_lsr_sum": "btc_z_top_lsr_sum",
        "z_taker_ratio": "btc_z_taker_ratio",
        "z_oi": "btc_z_oi",
    })
    print(f"  deriv snapshot non-null: z_oi_silent={snap_dz['btc_z_oi_silent'].notna().sum()}, z_top_lsr_sum={snap_dz['btc_z_top_lsr_sum'].notna().sum()}, z_taker_ratio={snap_dz['btc_z_taker_ratio'].notna().sum()}, z_oi={snap_dz['btc_z_oi'].notna().sum()}")

    # 5. Concatenate (preserve original order + columns)
    out = pd.concat([v3.reset_index(drop=True), snap_5m, snap_dz], axis=1)
    print(f"[4] output shape: {out.shape}  (input was {n_in} x {n_cols_in})")

    new_cols = ["btc_dist_ma200_5m", "btc_adx_14_5m",
                "btc_z_oi_silent", "btc_z_top_lsr_sum", "btc_z_taker_ratio", "btc_z_oi"]
    print("\n=== non-null counts (new cols) ===")
    for c in new_cols:
        nn = out[c].notna().sum()
        print(f"  {c:25s}: {nn}/{n_in} ({nn/n_in:.1%})")

    all6_nn = out[new_cols].notna().all(axis=1).sum()
    print(f"\nrows with ALL 6 new features non-null: {all6_nn}/{n_in} ({all6_nn/n_in:.1%})")

    out.to_csv(OUT_CSV, index=False)
    print(f"\n[5] wrote: {OUT_CSV}  ({len(out)} rows, {len(out.columns)} cols)")


if __name__ == "__main__":
    main()
