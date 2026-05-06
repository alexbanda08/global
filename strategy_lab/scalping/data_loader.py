"""5m OHLCV loader + feature engineering for scalping strategies.

Inputs:  data/binance/parquet/{SYM}/5m/year=*/part.parquet
Outputs: a single DataFrame per symbol with columns:
    open, high, low, close, volume, quote_volume, trades,
    taker_buy_base, taker_buy_quote,
    taker_buy_ratio,         # quote-volume buyer-initiated fraction (sellers if <0.5)
    range,                   # high - low
    body,                    # close - open
    is_red,                  # close < open
    vwap_session,            # daily-reset VWAP
    dist_vwap_pct,           # (close - vwap) / vwap (signed)
    ma_4h,                   # 48-bar SMA (4h on 5m)
    ma_24h,                  # 288-bar SMA
    atr_20,                  # Wilder ATR(20) on 5m
    rolling_range_med,       # 20-bar median high-low range
    vol_24h_quote,           # rolling 24h quote-volume sum
    vol_30d_quote_median,    # rolling 30d 24h-vol median
    rvol,                    # vol_24h / vol_30d_median
    session,                 # categorical: 'ASIA','LONDON','NY','OFF'
    bars_since_anchor,       # bars since last session anchor reset
    session_high, session_low,    # high/low since last session anchor
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_5M = ROOT / "data" / "binance" / "parquet"

BARS_PER_DAY = 12 * 24       # 288
BARS_PER_HOUR = 12

# Session anchors in UTC minutes
ANCHOR_MINUTES = {
    "ASIA":   0,            # 00:00 UTC (Tokyo open is ~00:00, Asia liquidity)
    "LONDON": 7 * 60,       # 07:00 UTC
    "NY":     13 * 60 + 30, # 13:30 UTC (NY equities open)
}


def load_5m(symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Concatenate all year-partitioned 5m parquets for `symbol`.

    `start` / `end` are ISO date strings to slice the result; both inclusive.
    """
    files = sorted(glob.glob(str(RAW_5M / symbol / "5m" / "year=*" / "part.parquet")))
    if not files:
        raise FileNotFoundError(f"no 5m data for {symbol} under {RAW_5M}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if start is not None:
        df = df.loc[start:]
    if end is not None:
        df = df.loc[:end]
    return df


def _session_label(idx: pd.DatetimeIndex) -> pd.Series:
    """ASIA / LONDON / NY / OFF labels per bar.

    Definitions (tutorial calls liquidity around opens):
      ASIA   : 00:00–06:55 UTC
      LONDON : 07:00–13:25 UTC
      NY     : 13:30–20:55 UTC
      OFF    : 21:00–23:55 UTC  (lowest crypto liquidity)
    """
    minute = idx.hour * 60 + idx.minute
    out = np.full(len(idx), "OFF", dtype=object)
    out[(minute >= 0) & (minute < 7 * 60)] = "ASIA"
    out[(minute >= 7 * 60) & (minute < 13 * 60 + 30)] = "LONDON"
    out[(minute >= 13 * 60 + 30) & (minute < 21 * 60)] = "NY"
    return pd.Series(out, index=idx, name="session")


def _bars_since_anchor(idx: pd.DatetimeIndex, sess: pd.Series) -> pd.Series:
    """For each bar, how many bars since the last session change."""
    boundary = sess.ne(sess.shift())
    grp = boundary.cumsum()
    out = grp.groupby(grp).cumcount()
    return out


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 20) -> np.ndarray:
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    if len(tr) < n:
        return out
    alpha = 1.0 / n
    out[n - 1] = np.nanmean(tr[:n])
    for i in range(n, len(tr)):
        out[i] = (1 - alpha) * out[i - 1] + alpha * tr[i]
    return out


def _session_vwap(df: pd.DataFrame, sess: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Daily-reset VWAP + session high/low.

    Reset key: UTC date (one VWAP per UTC day, traditional). Session label is
    used separately for entry-anchor proximity.
    """
    day = df.index.floor("1D")
    pv = df["close"] * df["quote_volume"]
    vwap = pv.groupby(day).cumsum() / df["quote_volume"].groupby(day).cumsum()
    s_high = df["high"].groupby(day).cummax()
    s_low = df["low"].groupby(day).cummin()
    vwap.name = "vwap_session"
    s_high.name = "session_high"
    s_low.name = "session_low"
    return vwap, s_high, s_low


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all derived columns to the 5m raw OHLCV.

    Note: in-place mutating return for clarity.
    """
    out = df.copy()

    # Buyer-initiated quote-volume fraction
    qv = out["quote_volume"].replace(0, np.nan)
    out["taker_buy_ratio"] = (out["taker_buy_quote"] / qv).clip(0, 1)

    # Bar shape
    out["range"] = out["high"] - out["low"]
    out["body"] = out["close"] - out["open"]
    out["is_red"] = (out["close"] < out["open"]).astype(np.int8)

    # Sessions + anchor distance
    sess = _session_label(out.index)
    out["session"] = sess.values
    out["bars_since_anchor"] = _bars_since_anchor(out.index, sess).values

    # VWAP + session high/low (UTC daily reset)
    vwap, sh, sl = _session_vwap(out, sess)
    out["vwap_session"] = vwap
    out["session_high"] = sh
    out["session_low"] = sl
    out["dist_vwap_pct"] = (out["close"] - out["vwap_session"]) / out["vwap_session"]

    # Moving averages on 5m
    out["ma_4h"] = out["close"].rolling(48, min_periods=12).mean()
    out["ma_24h"] = out["close"].rolling(BARS_PER_DAY, min_periods=24).mean()

    # ATR(20) and 20-bar median range
    out["atr_20"] = _wilder_atr(
        out["high"].to_numpy(dtype=float),
        out["low"].to_numpy(dtype=float),
        out["close"].to_numpy(dtype=float),
        n=20,
    )
    out["rolling_range_med"] = out["range"].rolling(20, min_periods=5).median()

    # 24h volume + 30d-of-24h-vol median (RVOL)
    out["vol_24h_quote"] = out["quote_volume"].rolling(BARS_PER_DAY, min_periods=BARS_PER_DAY).sum()
    out["vol_30d_quote_median"] = (
        out["vol_24h_quote"].rolling(30 * BARS_PER_DAY, min_periods=10 * BARS_PER_DAY).median()
    )
    out["rvol"] = out["vol_24h_quote"] / out["vol_30d_quote_median"]

    return out


def load_5m_with_features(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    extra: bool = False,
    vp_window: int = 60,
) -> pd.DataFrame:
    raw = load_5m(symbol, start=start, end=end)
    df = add_features(raw)
    if extra:
        # Lazy import to avoid circular dep in module-import order
        from features import add_extra
        df = add_extra(df, vp_window=vp_window)
    return df


if __name__ == "__main__":
    # Smoke test
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = load_5m_with_features(sym, start="2024-01-01", end="2024-12-31")
        print(f"{sym}: {len(df):,} bars | range {df.index[0]} → {df.index[-1]}")
        print(f"  cols: {list(df.columns)}")
        print(f"  taker_buy_ratio quantiles: "
              f"q10={df['taker_buy_ratio'].quantile(0.10):.3f}  "
              f"q50={df['taker_buy_ratio'].quantile(0.50):.3f}  "
              f"q90={df['taker_buy_ratio'].quantile(0.90):.3f}")
        print(f"  rvol describe:  median={df['rvol'].median():.2f}  q90={df['rvol'].quantile(0.90):.2f}")
