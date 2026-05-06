"""
build_dataset — assemble the labeled dataset for the V1 meta-classifier.

Universe:  data/v4/refresh_2026_05_02/btc_markets_minimal.csv (4,673 BTC markets, fresh today)
Outcome:   outcome_up (already in minimal CSV)
Features (one row per market):
  V3 enriched (left-joined where overlap):
    ret_5m, ret_15m, ret_1h, oi_*, ls_*, taker_*, book_skew, prob_a/b/c/stack, abs_move_pct
  Kronos predictions (left-joined where present in kronos_btc_predictions_full.csv):
    pred_dir_5m, pred_dir_15m, pred_ret_5m, pred_ret_15m
  ATR/ADX (computed at ctx_end_cest = window_start - 5min):
    atr_14, atr_pct, adx_14, plus_di_14, minus_di_14, atr_quantile_30d, adx_above_25
  Time features:
    hour_utc, dow_utc

Output:
  strategy_lab/data/meta_classifier/labeled_v1.parquet

Re-runnable: this script is read-only on inputs and idempotent on output.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

import os
ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / "strategy_lab" / "data" / "polymarket"
MIN_CSV = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
V3_CSV = PM / "btc_features_v3.csv"
BTC_5M = ROOT / "strategy_lab" / "kronos_ft" / "data" / "BTCUSDT_5m_ext.csv"
KRONOS_CSV = Path(os.environ.get("KRONOS_CSV_OVERRIDE",
    str(ROOT / "strategy_lab" / "results" / "kronos" / "kronos_btc_predictions_full.csv")))
DERIV_PANEL = ROOT / "data" / "v4" / "derivatives_zscore" / "panels" / "BTCUSDT_zscore.parquet"
OUT_DIR = ROOT / "strategy_lab" / "data" / "meta_classifier"
OUT_PARQUET = Path(os.environ.get("OUT_PARQUET_OVERRIDE", str(OUT_DIR / "labeled_v1.parquet")))

ATR_PERIOD = 14
ADX_PERIOD = 14
MA200_PERIOD = 200       # 200 bars on 5m = ~16.7h
RVOL_24H_BARS = 288      # 24h of 5m bars
RVOL_QUANT_DAYS = 30     # 30-day rolling window for realized vol quantile


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
    """MA-based and realized-vol regime features computed on the 5m series."""
    close = df["close"]
    ma200 = close.rolling(MA200_PERIOD, min_periods=MA200_PERIOD).mean()
    df["ma200"] = ma200
    df["above_ma200"] = (close > ma200).astype("Int8")
    df["price_vs_ma200_pct"] = (close - ma200) / ma200

    # Realized vol over trailing 24h (288 bars), as std of 5m log returns
    log_ret = np.log(close / close.shift(1))
    df["rvol_24h"] = log_ret.rolling(RVOL_24H_BARS, min_periods=RVOL_24H_BARS // 4).std()

    # Quantile of current rvol within the last 30d
    win = RVOL_QUANT_DAYS * 288
    df["rvol_quintile_30d"] = (
        df["rvol_24h"]
        .rolling(win, min_periods=win // 4)
        .apply(lambda x: int((x.iloc[-1] >= x).mean() * 5) if x.iloc[-1] == x.iloc[-1] else np.nan, raw=False)
    )
    return df


def add_atr_quantile(df: pd.DataFrame, lookback_days: int = 30, bars_per_day: int = 288) -> pd.DataFrame:
    """Where current ATR sits in the trailing 30d distribution (rank 0..1)."""
    win = lookback_days * bars_per_day  # 30d * 288 5min bars/day = 8640
    atr = df["atr_14"]
    # Rolling rank: position of current value within the trailing window
    df["atr_quantile_30d"] = (
        atr.rolling(win, min_periods=win // 4)
        .apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    )
    return df


def main():
    print("=== build_dataset ===")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Universe
    print(f"[1] loading universe: {MIN_CSV}")
    universe = pd.read_csv(MIN_CSV)
    universe = universe.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    universe["outcome_up"] = universe["outcome_up"].astype(int)
    universe["window_start_at_utc"] = pd.to_datetime(universe["window_start_unix"], unit="s", utc=True)
    universe["ctx_end_cest"] = (
        universe["window_start_at_utc"].dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
        - pd.Timedelta(minutes=5)
    )
    universe["hour_utc"] = universe["window_start_at_utc"].dt.hour
    universe["dow_utc"] = universe["window_start_at_utc"].dt.dayofweek
    print(f"  rows: {len(universe)}, tf split: {universe['timeframe'].value_counts().to_dict()}")
    print(f"  date range: {universe['window_start_at_utc'].min()} -> {universe['window_start_at_utc'].max()}")

    # 2. V3 features (left join on slug)
    print(f"[2] loading V3 features: {V3_CSV}")
    v3 = pd.read_csv(V3_CSV)
    v3_cols = [
        "slug", "abs_move_pct",
        "ret_5m", "ret_15m", "ret_1h",
        "oi_now", "oi_delta_5m", "oi_delta_15m", "oi_delta_1h", "oiv_delta_5m",
        "ls_count", "ls_count_delta_5m", "ls_top_count", "ls_top_sum",
        "smart_minus_retail", "taker_ratio", "taker_delta_5m",
        "book_skew", "entry_yes_ask", "entry_no_ask",
        "prob_a", "prob_b", "prob_c", "prob_stack",
    ]
    v3 = v3[[c for c in v3_cols if c in v3.columns]].drop_duplicates("slug")
    df = universe.merge(v3, on="slug", how="left")
    has_v3 = df["prob_a"].notna().sum()
    print(f"  V3 join: {has_v3}/{len(df)} have V3 features ({has_v3/len(df):.1%})")

    # 3. TA + price regime features from BTC 5m
    print(f"[3] computing ATR/ADX + MA200 + realized vol from {BTC_5M}")
    btc = pd.read_csv(BTC_5M)
    btc["timestamps"] = pd.to_datetime(btc["timestamps"])
    btc = btc.sort_values("timestamps").reset_index(drop=True)
    btc = add_atr_adx(btc, n=ATR_PERIOD)
    btc = add_atr_quantile(btc)
    btc = add_price_regime_features(btc)
    btc["adx_above_25"] = (btc["adx_14"] >= 25).astype("Int8")
    print(f"  5m bars: {len(btc):,}  range: {btc['timestamps'].min()} -> {btc['timestamps'].max()}")

    # snapshot at ctx_end_cest (= window_start - 5min)
    btc_idx = btc.set_index("timestamps")
    feat_cols = ["atr_14", "atr_pct", "adx_14", "plus_di_14", "minus_di_14",
                 "atr_quantile_30d", "adx_above_25",
                 "above_ma200", "price_vs_ma200_pct", "rvol_24h", "rvol_quintile_30d"]
    snap = btc_idx[feat_cols].reindex(df["ctx_end_cest"]).reset_index(drop=True)
    snap.columns = [f"ta_{c}" for c in snap.columns]
    df = pd.concat([df.reset_index(drop=True), snap], axis=1)
    has_ta = df["ta_atr_14"].notna().sum()
    print(f"  TA snapshot: {has_ta}/{len(df)} matched ({has_ta/len(df):.1%})")

    # 3b. Derivatives Z-score regime features (cross_institutional_lead, regime, etc)
    if DERIV_PANEL.exists():
        print(f"[3b] loading derivatives Z-score regime panel: {DERIV_PANEL}")
        deriv = pd.read_parquet(DERIV_PANEL)
        # deriv index is UTC timestamps; we need to match against window_start_at_utc
        # The panel is at 5-min cadence, ctx_end is window_start - 5m. Use ctx_end UTC for snapshot.
        df["ctx_end_utc"] = df["window_start_at_utc"] - pd.Timedelta(minutes=5)
        deriv_cols_to_use = [
            "funding_rate", "z_fund",
            "z_lsr", "brigalS",
            "z_top_lsr_count", "z_top_lsr_sum",
            "z_oi", "z_oi_silent", "oilsr",
            "z_taker_ratio", "z_dom_stables",
            "cross_institutional_lead", "cross_retail_lead",
            "cross_leverage_heat", "cross_risk_off", "cross_real_money",
            "score_bull_scaled", "score_bear_scaled", "regime",
        ]
        avail = [c for c in deriv_cols_to_use if c in deriv.columns]
        # Need tz-naive UTC for reindex against the deriv panel
        if hasattr(deriv.index, "tz") and deriv.index.tz is not None:
            deriv_idx = deriv.copy()
        else:
            deriv_idx = deriv
        snap2 = deriv_idx[avail].reindex(df["ctx_end_utc"]).reset_index(drop=True)
        snap2.columns = [f"dz_{c}" for c in snap2.columns]
        df = pd.concat([df.reset_index(drop=True), snap2], axis=1)
        has_dz = df["dz_z_lsr"].notna().sum() if "dz_z_lsr" in df.columns else 0
        print(f"  deriv-zscore snapshot: {has_dz}/{len(df)} matched ({has_dz/len(df):.1%})")
        # Encode regime (categorical) as one-hot if present
        if "dz_regime" in df.columns and df["dz_regime"].notna().sum() > 100:
            regime_dummies = pd.get_dummies(df["dz_regime"], prefix="dz_regime", dummy_na=False)
            df = pd.concat([df, regime_dummies.astype("Int8")], axis=1)
            print(f"  regime one-hot: {list(regime_dummies.columns)}")
    else:
        print(f"[3b] derivatives Z-score panel NOT FOUND: {DERIV_PANEL} (regime features skipped)")

    # 4. Kronos predictions (optional — file may not exist yet)
    if KRONOS_CSV.exists():
        print(f"[4] loading Kronos predictions: {KRONOS_CSV}")
        kr = pd.read_csv(KRONOS_CSV)
        kr_cols = ["slug", "pred_close_5m", "pred_close_15m", "pred_ret_5m", "pred_ret_15m", "pred_dir_5m", "pred_dir_15m"]
        kr = kr[[c for c in kr_cols if c in kr.columns]].drop_duplicates("slug")
        kr = kr.rename(columns={c: f"kr_{c}" for c in kr.columns if c != "slug"})
        df = df.merge(kr, on="slug", how="left")
        has_kr = df["kr_pred_dir_5m"].notna().sum()
        print(f"  Kronos join: {has_kr}/{len(df)} have predictions ({has_kr/len(df):.1%})")
    else:
        print(f"[4] Kronos predictions file not found yet (will be backfilled): {KRONOS_CSV}")
        for c in ["kr_pred_close_5m", "kr_pred_close_15m", "kr_pred_ret_5m", "kr_pred_ret_15m", "kr_pred_dir_5m", "kr_pred_dir_15m"]:
            df[c] = np.nan

    # Sort chronologically for time-series CV
    df = df.sort_values("window_start_unix").reset_index(drop=True)

    # Sanity: drop rows where the ATR/ADX snapshot couldn't be made (no 5m data covering)
    n_before = len(df)
    df = df.dropna(subset=["ta_atr_14"]).reset_index(drop=True)
    print(f"  dropped {n_before - len(df)} rows with missing ATR/ADX snapshot")

    # Persist
    df.to_parquet(OUT_PARQUET, index=False)
    print(f"\n[5] wrote: {OUT_PARQUET}  ({len(df)} rows, {len(df.columns)} cols)")
    print(f"  outcome_up balance: {df['outcome_up'].mean():.1%}")
    print(f"  Kronos coverage: {df['kr_pred_dir_5m'].notna().mean():.1%}")
    print(f"  V3 coverage: {df['prob_a'].notna().mean():.1%}")


if __name__ == "__main__":
    main()
