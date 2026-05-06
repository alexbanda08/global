"""Daily-resolution feature matrix for the regime classifier.

Assembles ~80 features per (asset, UTC_day) row. Uses:
  - 5m Binance OHLCV (data/binance/parquet/{sym}/5m/) for price-action +
    volume + money-flow features
  - 5m derivatives panel (data/v4/derivatives_zscore/panels/) for
    LSR / OI / funding / taker / cross-asset features (when available)
  - Spot 1h (data/v4/derivatives_zscore/spot/) for cross-asset relative
    strength

Output: one parquet per asset:
    strategy_lab/reports/regime_classifier/features_{sym}.parquet

The target column `target_up_next_day` = 1 if close on day t+1 > close on
day t, else 0.
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "strategy_lab" / "scalping"))

from data_loader import load_5m  # noqa: E402

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
OUT = ROOT / "strategy_lab" / "reports" / "regime_classifier"
OUT.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────
# Daily aggregation of 5m bars
# ─────────────────────────────────────────────────────────────────────
def aggregate_to_daily(df_5m: pd.DataFrame) -> pd.DataFrame:
    """Resample 5m OHLCV to daily UTC bars + compute intraday aggregates."""
    daily = pd.DataFrame()
    g = df_5m.groupby(df_5m.index.floor("1D"))
    daily["open"] = g["open"].first()
    daily["high"] = g["high"].max()
    daily["low"] = g["low"].min()
    daily["close"] = g["close"].last()
    daily["volume"] = g["volume"].sum()
    daily["quote_volume"] = g["quote_volume"].sum()
    daily["trades"] = g["trades"].sum()
    daily["taker_buy_base"] = g["taker_buy_base"].sum()
    daily["taker_buy_quote"] = g["taker_buy_quote"].sum()

    # Intraday aggression
    daily["taker_buy_ratio_day"] = daily["taker_buy_quote"] / daily["quote_volume"].replace(0, np.nan)
    daily["taker_delta_day"] = daily["taker_buy_quote"] - (daily["quote_volume"] - daily["taker_buy_quote"])

    # Intraday aggression-imbalance: fraction of 5m bars where taker_buy > 0.5
    bar_buy_dominant = (df_5m["taker_buy_quote"] / df_5m["quote_volume"].replace(0, np.nan)) > 0.5
    daily["aggression_imb_day"] = bar_buy_dominant.groupby(df_5m.index.floor("1D")).mean()

    # Intraday range stats
    daily["intraday_range"] = (daily["high"] - daily["low"]) / daily["close"]
    daily["body_pct"] = (daily["close"] - daily["open"]) / daily["open"]

    return daily


# ─────────────────────────────────────────────────────────────────────
# Price-action features
# ─────────────────────────────────────────────────────────────────────
def add_price_features(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    out["ret_1d"] = out["close"].pct_change(1)
    out["ret_3d"] = out["close"].pct_change(3)
    out["ret_7d"] = out["close"].pct_change(7)
    out["ret_30d"] = out["close"].pct_change(30)

    out["realized_vol_7d"] = out["ret_1d"].rolling(7).std() * np.sqrt(365)
    out["realized_vol_14d"] = out["ret_1d"].rolling(14).std() * np.sqrt(365)
    out["realized_vol_30d"] = out["ret_1d"].rolling(30).std() * np.sqrt(365)

    out["range_med_7d"] = out["intraday_range"].rolling(7).mean()
    out["range_compression"] = out["intraday_range"] / out["range_med_7d"].replace(0, np.nan)

    # MAs
    out["ma_20"] = out["close"].rolling(20).mean()
    out["ma_50"] = out["close"].rolling(50).mean()
    out["ma_200"] = out["close"].rolling(200).mean()
    out["dist_ma20_pct"] = (out["close"] - out["ma_20"]) / out["ma_20"]
    out["dist_ma50_pct"] = (out["close"] - out["ma_50"]) / out["ma_50"]
    out["dist_ma200_pct"] = (out["close"] - out["ma_200"]) / out["ma_200"]

    # Bollinger z-score
    bb_mean = out["close"].rolling(20).mean()
    bb_std = out["close"].rolling(20).std().replace(0, np.nan)
    out["bb_z_20"] = (out["close"] - bb_mean) / bb_std

    # RSI(14) on daily closes
    delta = out["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_up = up.rolling(14).mean()
    avg_dn = down.rolling(14).mean().replace(0, np.nan)
    rs = avg_up / avg_dn
    out["rsi_14"] = 100 - 100 / (1 + rs)

    # ADX(14) — trend strength
    high_diff = out["high"].diff()
    low_diff = -out["low"].diff()
    plus_dm = ((high_diff > low_diff) & (high_diff > 0)).astype(int) * high_diff.fillna(0)
    minus_dm = ((low_diff > high_diff) & (low_diff > 0)).astype(int) * low_diff.fillna(0)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - out["close"].shift()).abs(),
        (out["low"] - out["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    plus_di = 100 * plus_dm.rolling(14).sum() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(14).sum() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    out["adx_14"] = dx.rolling(14).mean()
    out["di_diff_14"] = plus_di - minus_di

    return out


# ─────────────────────────────────────────────────────────────────────
# Volume / money-flow features (daily versions)
# ─────────────────────────────────────────────────────────────────────
def add_volume_features(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    # OBV daily
    sign = np.sign(out["close"].diff().fillna(0)).astype(np.int8)
    out["obv"] = (sign * out["volume"]).fillna(0).cumsum()
    out["obv_slope_5d"] = out["obv"].diff(5)
    out["obv_slope_20d"] = out["obv"].diff(20)
    out["obv_z_20d"] = (out["obv_slope_5d"] - out["obv_slope_5d"].rolling(20).mean()) / \
                       out["obv_slope_5d"].rolling(20).std().replace(0, np.nan)

    # CMF(20)
    rng = (out["high"] - out["low"]).replace(0, np.nan)
    mfm = ((out["close"] - out["low"]) - (out["high"] - out["close"])) / rng
    mfv = mfm * out["volume"]
    out["cmf_20"] = mfv.rolling(20).sum() / out["volume"].rolling(20).sum().replace(0, np.nan)
    out["cmf_5"] = mfv.rolling(5).sum() / out["volume"].rolling(5).sum().replace(0, np.nan)

    # MFI(14)
    tp = (out["high"] + out["low"] + out["close"]) / 3.0
    rmf = tp * out["volume"]
    pos = rmf.where(tp.diff() > 0, 0.0)
    neg = rmf.where(tp.diff() < 0, 0.0)
    pos_sum = pos.rolling(14).sum()
    neg_sum = neg.rolling(14).sum().replace(0, np.nan)
    out["mfi_14"] = 100 - 100 / (1 + pos_sum / neg_sum)

    # Volume z-scores
    out["vol_z_20d"] = (out["volume"] - out["volume"].rolling(20).mean()) / \
                       out["volume"].rolling(20).std().replace(0, np.nan)
    out["vol_z_30d"] = (out["volume"] - out["volume"].rolling(30).mean()) / \
                       out["volume"].rolling(30).std().replace(0, np.nan)

    return out


# ─────────────────────────────────────────────────────────────────────
# Derivatives features (daily-aggregated from the 5m panel)
# ─────────────────────────────────────────────────────────────────────
DERIV_COLS = [
    "z_lsr", "z_oi", "z_oi_silent", "z_top_lsr_count", "z_top_lsr_sum",
    "z_taker_ratio", "z_fund", "brigalS", "oilsr",
    "cross_institutional_lead", "cross_retail_lead", "cross_leverage_heat",
    "cross_risk_off", "cross_real_money", "z_dom_stables", "z_cb_premium",
    "funding_rate", "score_bull_scaled", "score_bear_scaled",
]


def add_derivatives_features(d: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Merge daily-resolved derivatives panel features."""
    out = d.copy()
    panel_path = PANELS / f"{sym}_zscore.parquet"
    if not panel_path.exists():
        # Asset has no derivatives panel — skip
        for c in DERIV_COLS:
            out[c] = np.nan
            out[f"{c}_d1"] = np.nan
        return out

    panel = pd.read_parquet(panel_path)
    cols_present = [c for c in DERIV_COLS if c in panel.columns]
    daily_panel = panel[cols_present].resample("1D").last()

    for c in cols_present:
        out[c] = daily_panel[c].reindex(out.index)
        out[f"{c}_d1"] = out[c].diff(1)
    for c in DERIV_COLS:
        if c not in out.columns:
            out[c] = np.nan
            out[f"{c}_d1"] = np.nan

    # 7-day delta on cross-asset signals — captures regime transitions
    for c in ["cross_institutional_lead", "cross_leverage_heat", "z_lsr"]:
        if c in out.columns:
            out[f"{c}_d7"] = out[c].diff(7)

    return out


# ─────────────────────────────────────────────────────────────────────
# Cross-asset features (relative strength)
# ─────────────────────────────────────────────────────────────────────
def add_cross_asset(features: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Attach cross-asset relative-strength columns to each asset's frame."""
    if "BTCUSDT" in features and "ETHUSDT" in features:
        btc = features["BTCUSDT"]["ret_1d"]
        eth = features["ETHUSDT"]["ret_1d"]
        for sym in features:
            features[sym]["btc_ret_1d"] = btc.reindex(features[sym].index)
            features[sym]["eth_ret_1d"] = eth.reindex(features[sym].index)
            features[sym]["btc_minus_eth_1d"] = features[sym]["btc_ret_1d"] - features[sym]["eth_ret_1d"]
    if "SOLUSDT" in features:
        sol = features["SOLUSDT"]["ret_1d"]
        for sym in features:
            features[sym]["sol_ret_1d"] = sol.reindex(features[sym].index)
    return features


# ─────────────────────────────────────────────────────────────────────
# Calendar features
# ─────────────────────────────────────────────────────────────────────
def add_calendar(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    idx = out.index
    out["dow"] = idx.dayofweek          # 0=Mon, 6=Sun
    out["dow_sin"] = np.sin(2 * np.pi * idx.dayofweek / 7)
    out["dow_cos"] = np.cos(2 * np.pi * idx.dayofweek / 7)
    out["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    out["month"] = idx.month
    return out


# ─────────────────────────────────────────────────────────────────────
# Target
# ─────────────────────────────────────────────────────────────────────
def add_target(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    out["close_next"] = out["close"].shift(-1)
    out["target_up_next_day"] = (out["close_next"] > out["close"]).astype(int)
    # For diagnostics: signed next-day return
    out["next_day_ret"] = out["close_next"] / out["close"] - 1.0
    return out


# ─────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────
def build_features_for_symbol(sym: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    print(f"[{sym}] loading 5m…", flush=True)
    df_5m = load_5m(sym, start=start, end=end)
    print(f"[{sym}] aggregating to daily…", flush=True)
    daily = aggregate_to_daily(df_5m)
    print(f"[{sym}] adding price features…", flush=True)
    daily = add_price_features(daily)
    print(f"[{sym}] adding volume features…", flush=True)
    daily = add_volume_features(daily)
    print(f"[{sym}] adding derivatives features…", flush=True)
    daily = add_derivatives_features(daily, sym)
    print(f"[{sym}] adding calendar…", flush=True)
    daily = add_calendar(daily)
    print(f"[{sym}] adding target…", flush=True)
    daily = add_target(daily)
    return daily


def build_all(symbols: list[str], start: str = "2018-01-01", end: str = "2026-03-31") -> dict[str, pd.DataFrame]:
    features = {}
    for sym in symbols:
        features[sym] = build_features_for_symbol(sym, start=start, end=end)
    print("Adding cross-asset features…", flush=True)
    features = add_cross_asset(features)
    return features


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-03-31")
    args = ap.parse_args()

    features = build_all(args.symbols, start=args.start, end=args.end)
    for sym, df in features.items():
        path = OUT / f"features_{sym}.parquet"
        df.to_parquet(path)
        n_features = len([c for c in df.columns if c not in
                          ("close_next", "target_up_next_day", "next_day_ret")])
        print(f"\n{sym}: {len(df):,} rows × {n_features} features → {path}")
        # Diagnostics
        valid = df.dropna(subset=["target_up_next_day", "ret_1d"])
        ud_rate = valid["target_up_next_day"].mean()
        print(f"  rows with target valid: {len(valid):,}")
        print(f"  base rate (always-up): {ud_rate*100:.2f}%")
        print(f"  date range: {valid.index[0].date()} → {valid.index[-1].date()}")
