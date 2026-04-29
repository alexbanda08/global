"""
1h feature matrix — mirrors features_15m.py but aggregates to 1h bars.

Sources:
  OHLCV 1h   (existing resampled parquet)
  metrics 5m → 1h last/mean
  funding 8h (ffill)
  premium 1h (native)
  liquidations 1m → 1h sum
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import talib

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_parquet_glob(pattern: str) -> pd.DataFrame:
    files = sorted(Path(DATA).glob(pattern))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()


def load_ohlcv_1h(sym: str) -> pd.DataFrame:
    df = _load_parquet_glob(f"binance/parquet/{sym}/1h/year=*/part.parquet")
    df = df.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    return df[["open","high","low","close","volume"]].astype("float64")


def load_metrics(sym: str) -> pd.DataFrame:
    df = _load_parquet_glob(f"binance/futures/metrics/{sym}/parquet/year=*/part.parquet")
    if df.empty: return df
    df = df.drop_duplicates("create_time").sort_values("create_time").set_index("create_time")
    return df[["sum_open_interest","sum_open_interest_value",
               "count_toptrader_long_short_ratio","sum_toptrader_long_short_ratio",
               "count_long_short_ratio","sum_taker_long_short_vol_ratio"]].astype("float64")


def load_funding(sym: str) -> pd.DataFrame:
    p = DATA/"binance"/"futures"/"fundingRate"/sym/"parquet"/"fundingRate.parquet"
    if not p.exists(): return pd.DataFrame()
    df = pd.read_parquet(p).drop_duplicates("calc_time").sort_values("calc_time").set_index("calc_time")
    return df[["last_funding_rate"]].astype("float64")


def load_premium(sym: str) -> pd.DataFrame:
    p = DATA/"binance"/"futures"/"premiumIndexKlines"/sym/"1h"/"parquet"/"premium_1h.parquet"
    if not p.exists(): return pd.DataFrame()
    df = pd.read_parquet(p).drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    return df[["close"]].rename(columns={"close":"premium_1h"}).astype("float64")


def load_liquidations(sym: str) -> pd.DataFrame:
    d = DATA/"coinapi"/"liquidations"/sym
    if not d.exists(): return pd.DataFrame()
    liq_q = pd.read_parquet(d/"LIQUIDATION_QUANTITY.parquet")
    liq_p = pd.read_parquet(d/"LIQUIDATION_AVERAGE_PRICE.parquet")
    liq_q = liq_q[["time_period_start","count","sum"]].rename(columns={"count":"liq_count","sum":"liq_qty"})
    liq_p = liq_p[["time_period_start","last"]].rename(columns={"last":"liq_avg_price"})
    df = liq_q.merge(liq_p, on="time_period_start", how="left").set_index("time_period_start").sort_index()
    df["liq_notional_usd"] = df["liq_qty"] * df["liq_avg_price"]
    return df[["liq_count","liq_qty","liq_notional_usd"]]


def _resample(src, how, idx):
    if src.empty: return pd.DataFrame(index=idx)
    src = src.copy()
    src.index = pd.to_datetime(src.index, utc=True)
    return src.resample("1h", label="left", closed="left").agg(how).reindex(idx, method="ffill")


def build(sym: str) -> pd.DataFrame:
    print(f"=== {sym} ===", flush=True)
    ohlc = load_ohlcv_1h(sym)
    print(f"  ohlc 1h: {len(ohlc):,} bars")
    c = ohlc["close"]; h = ohlc["high"]; l = ohlc["low"]

    # Price
    ohlc["ret_1"] = c.pct_change()
    ohlc["ret_4"] = c.pct_change(4)
    ohlc["ret_12"] = c.pct_change(12)
    ohlc["atr_14"] = talib.ATR(h.values, l.values, c.values, 14)
    ohlc["realized_vol_24"] = ohlc["ret_1"].rolling(24).std() * np.sqrt(24 * 365)

    body_max = np.maximum(ohlc["open"], ohlc["close"])
    body_min = np.minimum(ohlc["open"], ohlc["close"])
    rng = (h - l).replace(0, np.nan)
    ohlc["wick_up_frac"] = (h - body_max) / rng
    ohlc["wick_dn_frac"] = (body_min - l) / rng

    # Regime from daily EMA200
    daily = c.resample("1D").last().dropna()
    ema200_d = daily.ewm(span=200, adjust=False).mean()
    slope_60 = ema200_d - ema200_d.shift(60)
    bull = ((daily > ema200_d) & (slope_60 > 0)).shift(1).reindex(ohlc.index, method="ffill").fillna(False)
    ohlc["regime_bull"] = bull.astype(int)

    # Metrics (5m → 1h)
    met = load_metrics(sym)
    if not met.empty:
        print(f"  metrics: {len(met):,} rows")
        m1h = _resample(met, {
            "sum_open_interest":"last", "sum_open_interest_value":"last",
            "count_toptrader_long_short_ratio":"last",
            "sum_toptrader_long_short_ratio":"last",
            "count_long_short_ratio":"last",
            "sum_taker_long_short_vol_ratio":"mean",
        }, ohlc.index)
        ohlc = ohlc.join(m1h)
        ohlc["oi_pct_chg_4"]  = ohlc["sum_open_interest"].pct_change(4)     # 4h OI change
        ohlc["oi_pct_chg_24"] = ohlc["sum_open_interest"].pct_change(24)    # 1d OI change
        tr = ohlc["sum_taker_long_short_vol_ratio"]
        # 7-day z-score = 168 bars at 1h
        ohlc["taker_ratio_z_7d"] = (tr - tr.rolling(168).mean()) / tr.rolling(168).std()
        tl = ohlc["sum_toptrader_long_short_ratio"]
        ohlc["top_trader_ls_z_7d"] = (tl - tl.rolling(168).mean()) / tl.rolling(168).std()

    fr = load_funding(sym)
    if not fr.empty:
        fr1h = fr.reindex(ohlc.index, method="ffill")
        v = fr1h["last_funding_rate"]
        ohlc["funding_rate"] = v
        ohlc["funding_rate_z_30d"] = (v - v.rolling(30*24).mean()) / v.rolling(30*24).std()

    pr = load_premium(sym)
    if not pr.empty:
        pr1h = pr.reindex(ohlc.index, method="ffill")
        v = pr1h["premium_1h"]
        ohlc["premium_1h"] = v
        ohlc["premium_z_30d"] = (v - v.rolling(30*24).mean()) / v.rolling(30*24).std()

    liq = load_liquidations(sym)
    if not liq.empty:
        l1h = _resample(liq, {"liq_count":"sum","liq_qty":"sum","liq_notional_usd":"sum"}, ohlc.index).fillna(0)
        ohlc = ohlc.join(l1h)
        ln = ohlc["liq_notional_usd"].fillna(0)
        ohlc["liq_notional_z_7d"] = (ln - ln.rolling(168).mean()) / (ln.rolling(168).std() + 1e-9)

    # Target: next-bar open->close return
    ohlc["target_ret_1"] = ohlc["close"].shift(-1) / ohlc["open"].shift(-1) - 1
    ohlc["target_ret_4"] = ohlc["close"].shift(-4) / ohlc["open"].shift(-1) - 1

    out = ROOT/"strategy_lab"/"features"/f"{sym}_1h_features.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    ohlc.to_parquet(out, engine="pyarrow", compression="zstd")
    print(f"  saved -> {out.name} ({len(ohlc):,} rows x {len(ohlc.columns)} cols)")
    return ohlc


def main():
    for sym in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
        build(sym)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main() or 0)
