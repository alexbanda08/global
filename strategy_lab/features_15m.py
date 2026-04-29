"""
Build a unified 15m feature matrix per symbol by merging:

  * spot OHLCV 15m           (data/binance/parquet/<SYM>/15m/)
  * metrics (5m)             (data/binance/futures/metrics/<SYM>/)
    - OI (sum_open_interest)
    - top trader long/short
    - long/short ratio
    - taker buy/sell vol ratio
  * funding rate (8h)        (data/binance/futures/fundingRate/)
  * premium index 1h         (data/binance/futures/premiumIndexKlines/)
  * liquidations 1m          (data/coinapi/liquidations/)

Features engineered (all bar-ending so next-bar return is the label):
    close return past 1/4/8 bars
    atr_14                                  (price volatility)
    realized_vol_24_pct                     (24 bar rolling std of returns)
    taker_ratio_z_7d                        (buy/sell flow z-score)
    oi_pct_chg_4bar                         (OI change last 1h)
    oi_pct_chg_24bar                        (OI change last 6h)
    top_trader_ls_z_7d
    funding_rate_z_30d
    premium_z_30d
    liq_count_15m                           (number of liquidation events)
    liq_notional_15m                        (total USD liquidated)
    liq_notional_z_7d
    bar_wick_up_frac, bar_wick_dn_frac
    regime_bull   (0/1)                     close > ema200d
    regime_slope_pos                        ema200d slope > 0
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import talib

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_parquet_glob(pattern: str, cols: list[str] | None = None) -> pd.DataFrame:
    files = sorted(Path(DATA).glob(pattern))
    dfs = [pd.read_parquet(f, columns=cols) for f in files]
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def load_ohlcv_15m(sym: str) -> pd.DataFrame:
    df = _load_parquet_glob(f"binance/parquet/{sym}/15m/year=*/part.parquet")
    df = df.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    return df[["open","high","low","close","volume"]].astype("float64")


def load_metrics(sym: str) -> pd.DataFrame:
    """5-minute perp metrics: OI, LS ratios, taker ratio."""
    df = _load_parquet_glob(f"binance/futures/metrics/{sym}/parquet/year=*/part.parquet")
    if df.empty: return df
    df = (df.drop_duplicates("create_time")
            .sort_values("create_time")
            .set_index("create_time"))
    cols = ["sum_open_interest", "sum_open_interest_value",
            "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
            "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]
    df = df[cols].astype("float64")
    return df


def load_funding(sym: str) -> pd.DataFrame:
    p = DATA / "binance" / "futures" / "fundingRate" / sym / "parquet" / "fundingRate.parquet"
    if not p.exists(): return pd.DataFrame()
    df = pd.read_parquet(p).drop_duplicates("calc_time").sort_values("calc_time").set_index("calc_time")
    return df[["last_funding_rate"]].astype("float64")


def load_premium_1h(sym: str) -> pd.DataFrame:
    p = DATA / "binance" / "futures" / "premiumIndexKlines" / sym / "1h" / "parquet" / "premium_1h.parquet"
    if not p.exists(): return pd.DataFrame()
    df = pd.read_parquet(p).drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    return df[["close"]].rename(columns={"close":"premium_1h"}).astype("float64")


def load_liquidations(sym: str) -> pd.DataFrame:
    """Liquidation count + notional aggregated per minute → resampled to 15m."""
    d = DATA / "coinapi" / "liquidations" / sym
    if not d.exists(): return pd.DataFrame()
    liq_q = pd.read_parquet(d / "LIQUIDATION_QUANTITY.parquet")
    liq_p = pd.read_parquet(d / "LIQUIDATION_AVERAGE_PRICE.parquet")
    # count = # liquidations that minute; sum = total base-asset quantity
    liq_q = liq_q[["time_period_start","count","sum"]].rename(
        columns={"count":"liq_count","sum":"liq_qty"})
    liq_p = liq_p[["time_period_start","last"]].rename(columns={"last":"liq_avg_price"})
    df = liq_q.merge(liq_p, on="time_period_start", how="left")
    df = df.set_index("time_period_start").sort_index()
    df["liq_notional_usd"] = df["liq_qty"] * df["liq_avg_price"]
    return df[["liq_count","liq_qty","liq_notional_usd"]]


def _resample_to_15m(src: pd.DataFrame, how: dict, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Align a higher-frequency series to a 15m grid using the provided agg rules.
       `how` is a column→agg dict (e.g. {'oi':'last','liq_count':'sum'})."""
    if src.empty: return pd.DataFrame(index=idx)
    # group to 15m buckets aligned to 00/15/30/45 minutes
    src = src.copy()
    src.index = pd.to_datetime(src.index, utc=True)
    out = src.resample("15min", label="left", closed="left").agg(how)
    out = out.reindex(idx, method="ffill")
    return out


def build(sym: str) -> pd.DataFrame:
    print(f"=== {sym} ===", flush=True)
    ohlc = load_ohlcv_15m(sym)
    print(f"  ohlc 15m: {len(ohlc):,} bars  {ohlc.index.min()} -> {ohlc.index.max()}")

    # Core price features
    c = ohlc["close"]; h = ohlc["high"]; l = ohlc["low"]
    ohlc["ret_1"]  = c.pct_change(1)
    ohlc["ret_4"]  = c.pct_change(4)
    ohlc["ret_8"]  = c.pct_change(8)
    ohlc["atr_14"] = talib.ATR(h.values, l.values, c.values, 14)
    ohlc["realized_vol_24"] = ohlc["ret_1"].rolling(24).std() * np.sqrt(24 * 4 * 365)

    # Wick fractions
    body_max = np.maximum(ohlc["open"], ohlc["close"])
    body_min = np.minimum(ohlc["open"], ohlc["close"])
    rng = (h - l).replace(0, np.nan)
    ohlc["wick_up_frac"] = (h - body_max) / rng
    ohlc["wick_dn_frac"] = (body_min - l) / rng

    # Regime on daily close (shifted 1 day to avoid peek)
    daily = c.resample("1D").last().dropna()
    ema200_d = daily.ewm(span=200, adjust=False).mean()
    slope_60 = ema200_d - ema200_d.shift(60)
    bull_d = ((daily > ema200_d) & (slope_60 > 0)).shift(1).reindex(ohlc.index, method="ffill").fillna(False)
    ohlc["regime_bull"] = bull_d.astype(int)

    # ---- metrics (5m → 15m) ----
    met = load_metrics(sym)
    if not met.empty:
        print(f"  metrics 5m: {len(met):,} rows")
        m15 = _resample_to_15m(
            met,
            {
                "sum_open_interest": "last",
                "sum_open_interest_value": "last",
                "count_toptrader_long_short_ratio": "last",
                "sum_toptrader_long_short_ratio":   "last",
                "count_long_short_ratio":           "last",
                "sum_taker_long_short_vol_ratio":   "mean",   # average over the 15m
            },
            ohlc.index,
        )
        ohlc = ohlc.join(m15)
        ohlc["oi_pct_chg_4"]  = ohlc["sum_open_interest"].pct_change(4)
        ohlc["oi_pct_chg_24"] = ohlc["sum_open_interest"].pct_change(24)
        # taker ratio z-score over 7 days (7*24*4=672 bars)
        tr = ohlc["sum_taker_long_short_vol_ratio"]
        ohlc["taker_ratio_z_7d"] = (tr - tr.rolling(672).mean()) / tr.rolling(672).std()
        # top-trader LS z-score
        tl = ohlc["sum_toptrader_long_short_ratio"]
        ohlc["top_trader_ls_z_7d"] = (tl - tl.rolling(672).mean()) / tl.rolling(672).std()

    # ---- funding rate (8h → 15m, ffill) ----
    fr = load_funding(sym)
    if not fr.empty:
        print(f"  funding: {len(fr):,} rows")
        fr15 = fr.reindex(ohlc.index, method="ffill")
        # 30-day z (30*24*4/8 → just use full-history z for simplicity)
        v = fr15["last_funding_rate"]
        ohlc["funding_rate"] = v
        ohlc["funding_rate_z_30d"] = (v - v.rolling(30*24*4).mean()) / v.rolling(30*24*4).std()

    # ---- premium index 1h (→ 15m, ffill) ----
    pr = load_premium_1h(sym)
    if not pr.empty:
        print(f"  premium 1h: {len(pr):,} rows")
        pr15 = pr.reindex(ohlc.index, method="ffill")
        v = pr15["premium_1h"]
        ohlc["premium_1h"] = v
        ohlc["premium_z_30d"] = (v - v.rolling(30*24*4).mean()) / v.rolling(30*24*4).std()

    # ---- liquidations (1m → 15m, sum) ----
    liq = load_liquidations(sym)
    if not liq.empty:
        print(f"  liquidations 1m: {len(liq):,} rows")
        l15 = _resample_to_15m(
            liq,
            {"liq_count": "sum", "liq_qty": "sum", "liq_notional_usd": "sum"},
            ohlc.index,
        )
        l15 = l15.fillna(0)
        ohlc = ohlc.join(l15)
        ln = ohlc["liq_notional_usd"].fillna(0)
        # 7-day z-score (672 bars of 15m)
        ohlc["liq_notional_z_7d"] = (ln - ln.rolling(672).mean()) / (ln.rolling(672).std() + 1e-9)

    # Target: next-bar close-to-close return (what we'd earn if we entered at next-bar open)
    ohlc["target_ret_1"] = ohlc["close"].shift(-1) / ohlc["open"].shift(-1) - 1
    ohlc["target_ret_4"] = ohlc["close"].shift(-4) / ohlc["open"].shift(-1) - 1

    out = ROOT / "strategy_lab" / "features" / f"{sym}_15m_features.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    ohlc.to_parquet(out, engine="pyarrow", compression="zstd")
    print(f"  saved -> {out.name}  ({len(ohlc):,} rows × {len(ohlc.columns)} cols, "
          f"{out.stat().st_size/1024/1024:.1f} MB)")
    return ohlc


def main():
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        build(sym)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main() or 0)
