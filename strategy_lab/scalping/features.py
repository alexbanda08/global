"""Extended feature library for crypto scalping.

Adds order-flow + volume-distribution indicators to the basic OHLCV+VWAP set:

  Volume / money flow:
    - obv                  : On-Balance Volume (cumulative volume signed by price ∆)
    - obv_slope_20         : OBV slope over last 20 bars (trend confirmation)
    - cmf_20               : Chaikin Money Flow over 20 bars [-1..+1]
    - mfi_14               : Money Flow Index (volume-weighted RSI) [0..100]
    - ad_line              : Accumulation / Distribution Line (cumulative)
    - vol_z_20             : Volume z-score over last 20 bars (spike detector)

  Aggression / order flow:
    - taker_delta          : taker_buy_quote − taker_sell_quote (per bar)
    - taker_delta_z_20     : 20-bar z-score of taker_delta (aggression spikes)
    - cum_delta_session    : cumulative taker_delta since session reset (UTC daily)
    - aggression_imbalance : ratio of bars in last 20 where taker_buy_ratio > 0.5

  Volume profile (rolling N-bar window):
    - vp_poc_60            : Point of Control (price level with most volume in last 60 bars)
    - vp_vah_60            : Value Area High (top 70% volume bound)
    - vp_val_60            : Value Area Low  (bottom 70% volume bound)
    - dist_poc_pct         : (close − vp_poc) / close (signed, in %)
    - inside_value_area    : 1 if vp_val < close < vp_vah else 0

  VWAP bands:
    - vwap_band_upper_2    : VWAP + 2σ (rolling 20-bar stdev of price-VWAP)
    - vwap_band_lower_2    : VWAP − 2σ
    - vwap_band_upper_3    : VWAP + 3σ (extreme stretch)
    - vwap_band_lower_3    : VWAP − 3σ
    - dist_vwap_sigma      : (close − vwap) / sigma  (z-score in σ units)

  Liquidity / sweep features:
    - session_high_breach  : 1 if high of bar exceeds running session high before this bar
    - session_low_breach   : mirror
    - sweep_reclaim_high   : 1 if high breached session_high then close < session_high (failed)
    - sweep_reclaim_low    : 1 if low broke session_low then close > session_low (failed)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BARS_PER_DAY = 288  # 5m bars in 24h


# ─────────────────────────────────────────────────────────────────────
# Volume / money flow
# ─────────────────────────────────────────────────────────────────────
def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    sign = np.sign(close.diff().fillna(0)).astype(np.int8)
    return (sign * volume).fillna(0).cumsum().rename("obv")


def cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 20) -> pd.Series:
    """Chaikin Money Flow over n bars. Range [-1, +1]."""
    rng = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    mfv = mfm * volume
    out = mfv.rolling(n, min_periods=n).sum() / volume.rolling(n, min_periods=n).sum()
    return out.rename(f"cmf_{n}")


def mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 14) -> pd.Series:
    """Money Flow Index — volume-weighted RSI."""
    tp = (high + low + close) / 3.0
    rmf = tp * volume  # raw money flow
    pos = rmf.where(tp.diff() > 0, 0.0)
    neg = rmf.where(tp.diff() < 0, 0.0)
    pos_sum = pos.rolling(n, min_periods=n).sum()
    neg_sum = neg.rolling(n, min_periods=n).sum().replace(0, np.nan)
    mr = pos_sum / neg_sum
    out = 100.0 - (100.0 / (1.0 + mr))
    return out.rename(f"mfi_{n}")


def ad_line(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Accumulation/Distribution Line — cumulative CMF money-flow."""
    rng = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    return (mfm * volume).fillna(0).cumsum().rename("ad_line")


def volume_z(volume: pd.Series, n: int = 20) -> pd.Series:
    """Z-score of bar volume vs trailing mean/std."""
    m = volume.rolling(n, min_periods=n).mean()
    s = volume.rolling(n, min_periods=n).std().replace(0, np.nan)
    return ((volume - m) / s).rename(f"vol_z_{n}")


# ─────────────────────────────────────────────────────────────────────
# Aggression / order-flow delta (Binance taker fields)
# ─────────────────────────────────────────────────────────────────────
def taker_delta(taker_buy_quote: pd.Series, quote_volume: pd.Series) -> pd.Series:
    """Taker buy − sell quote-volume per bar (positive = aggressive buying)."""
    taker_sell_quote = quote_volume - taker_buy_quote
    return (taker_buy_quote - taker_sell_quote).rename("taker_delta")


def taker_delta_z(td: pd.Series, n: int = 20) -> pd.Series:
    m = td.rolling(n, min_periods=n).mean()
    s = td.rolling(n, min_periods=n).std().replace(0, np.nan)
    return ((td - m) / s).rename(f"taker_delta_z_{n}")


def cum_delta_session(td: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """Cumulative taker_delta since UTC midnight reset."""
    day = pd.Series(idx.floor("1D"), index=idx)
    grp = td.groupby(day)
    return grp.cumsum().rename("cum_delta_session")


def aggression_imbalance(taker_buy_ratio: pd.Series, n: int = 20) -> pd.Series:
    """Fraction of last n bars where taker_buy_ratio > 0.5 (buyer-dominant)."""
    is_buy = (taker_buy_ratio > 0.5).astype(np.int8)
    return is_buy.rolling(n, min_periods=n).mean().rename(f"aggression_imb_{n}")


# ─────────────────────────────────────────────────────────────────────
# Volume profile (rolling)
# ─────────────────────────────────────────────────────────────────────
def _vp_window(prices: np.ndarray, vols: np.ndarray, n_bins: int = 30) -> tuple[float, float, float]:
    """Compute POC / VAH / VAL for a single window. Vectorized via histogram.

    Returns (poc_price, val, vah). VA contains 70% of total volume around POC.
    """
    if len(prices) < 5 or vols.sum() <= 0:
        return (np.nan, np.nan, np.nan)
    p_min, p_max = prices.min(), prices.max()
    if p_max <= p_min:
        return (float(prices[0]), float(prices[0]), float(prices[0]))
    hist, edges = np.histogram(prices, bins=n_bins, range=(p_min, p_max), weights=vols)
    bin_mids = (edges[:-1] + edges[1:]) / 2.0
    poc_idx = int(np.argmax(hist))
    poc = float(bin_mids[poc_idx])
    total = hist.sum()
    target = 0.70 * total
    # Expand symmetrically around POC until 70% is captured
    lo = hi = poc_idx
    accum = hist[poc_idx]
    while accum < target and (lo > 0 or hi < n_bins - 1):
        lo_val = hist[lo - 1] if lo > 0 else -1
        hi_val = hist[hi + 1] if hi < n_bins - 1 else -1
        if hi_val >= lo_val:
            hi += 1
            accum += hist[hi]
        else:
            lo -= 1
            accum += hist[lo]
    val = float(edges[lo])
    vah = float(edges[hi + 1])
    return (poc, val, vah)


def volume_profile_rolling(close: pd.Series, volume: pd.Series, window: int = 60, n_bins: int = 30) -> pd.DataFrame:
    """Rolling volume-profile POC/VAL/VAH over the last `window` bars.

    Slow (loop-per-bar) but acceptable for one-off backtest. We avoid recomputing
    the histogram every bar by stride iteration.
    """
    n = len(close)
    out = np.full((n, 3), np.nan, dtype=float)
    p = close.to_numpy(dtype=float)
    v = volume.to_numpy(dtype=float)
    for i in range(window - 1, n):
        out[i] = _vp_window(p[i - window + 1 : i + 1], v[i - window + 1 : i + 1], n_bins=n_bins)
    return pd.DataFrame(out, index=close.index, columns=["vp_poc", "vp_val", "vp_vah"])


# ─────────────────────────────────────────────────────────────────────
# VWAP bands
# ─────────────────────────────────────────────────────────────────────
def vwap_bands(close: pd.Series, vwap: pd.Series, n: int = 20, mults: tuple[float, ...] = (2.0, 3.0)) -> pd.DataFrame:
    """VWAP ± k×σ bands (σ = rolling stdev of close − vwap)."""
    diff = close - vwap
    sigma = diff.rolling(n, min_periods=n).std()
    out = pd.DataFrame(index=close.index)
    for m in mults:
        out[f"vwap_band_upper_{int(m)}"] = vwap + m * sigma
        out[f"vwap_band_lower_{int(m)}"] = vwap - m * sigma
    out["vwap_sigma"] = sigma
    out["dist_vwap_sigma"] = diff / sigma.replace(0, np.nan)
    return out


# ─────────────────────────────────────────────────────────────────────
# Liquidity / sweep features
# ─────────────────────────────────────────────────────────────────────
def sweep_features(df: pd.DataFrame) -> pd.DataFrame:
    """Detect session-high/low BREACHES and SWEEP-RECLAIMS.

    A "sweep" = bar that breaches the prior session high/low, then closes back
    inside. These trap-and-reverse bars are quintessential crypto liquidity
    grabs around session opens.
    """
    sh_prev = df["session_high"].shift(1)  # session high BEFORE the current bar
    sl_prev = df["session_low"].shift(1)
    out = pd.DataFrame(index=df.index)
    out["session_high_breach"] = (df["high"] > sh_prev).astype(np.int8)
    out["session_low_breach"] = (df["low"] < sl_prev).astype(np.int8)
    out["sweep_reclaim_high"] = (
        (df["high"] > sh_prev) & (df["close"] < sh_prev)
    ).astype(np.int8)
    out["sweep_reclaim_low"] = (
        (df["low"] < sl_prev) & (df["close"] > sl_prev)
    ).astype(np.int8)
    return out


# ─────────────────────────────────────────────────────────────────────
# Master add_extra(df) — wires everything onto a 5m feature DataFrame
# ─────────────────────────────────────────────────────────────────────
def add_extra(df: pd.DataFrame, vp_window: int = 60, vp_bins: int = 30) -> pd.DataFrame:
    """Append the full extended-features set to the loader output.

    Inputs: df must already have basic features (open/high/low/close/volume,
    quote_volume, taker_buy_quote, taker_buy_ratio, vwap_session, session_high,
    session_low). See data_loader.add_features().
    """
    out = df.copy()

    # Volume / money flow
    out["obv"] = obv(out["close"], out["volume"])
    out["obv_slope_20"] = out["obv"].diff(20)
    out["cmf_20"] = cmf(out["high"], out["low"], out["close"], out["volume"], n=20)
    out["mfi_14"] = mfi(out["high"], out["low"], out["close"], out["volume"], n=14)
    out["ad_line"] = ad_line(out["high"], out["low"], out["close"], out["volume"])
    out["vol_z_20"] = volume_z(out["volume"], n=20)

    # Aggression / delta
    td = taker_delta(out["taker_buy_quote"], out["quote_volume"])
    out["taker_delta"] = td
    out["taker_delta_z_20"] = taker_delta_z(td, n=20)
    out["cum_delta_session"] = cum_delta_session(td, out.index)
    out["aggression_imb_20"] = aggression_imbalance(out["taker_buy_ratio"], n=20)

    # VWAP bands
    bands = vwap_bands(out["close"], out["vwap_session"], n=20, mults=(2.0, 3.0))
    for c in bands.columns:
        out[c] = bands[c]

    # Volume profile (rolling 60-bar = 5h window)
    vp = volume_profile_rolling(out["close"], out["volume"], window=vp_window, n_bins=vp_bins)
    for c in vp.columns:
        out[f"{c}_{vp_window}"] = vp[c]
    poc_col = f"vp_poc_{vp_window}"
    val_col = f"vp_val_{vp_window}"
    vah_col = f"vp_vah_{vp_window}"
    out["dist_poc_pct"] = (out["close"] - out[poc_col]) / out["close"]
    out["inside_value_area"] = ((out["close"] > out[val_col]) & (out["close"] < out[vah_col])).astype(np.int8)

    # Sweep features
    sw = sweep_features(out)
    for c in sw.columns:
        out[c] = sw[c]

    return out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from data_loader import load_5m_with_features

    df = load_5m_with_features("BTCUSDT", start="2024-06-01", end="2024-06-30")
    df = add_extra(df, vp_window=60)
    extra_cols = [c for c in df.columns if any(k in c for k in
                  ["obv", "cmf", "mfi", "ad_line", "vol_z", "taker_delta",
                   "cum_delta", "aggression", "vp_", "dist_poc", "inside_value",
                   "vwap_band", "dist_vwap_sigma", "sweep", "breach"])]
    print(f"Extra cols added: {len(extra_cols)}")
    for c in extra_cols:
        n_nonan = df[c].notna().sum()
        print(f"  {c:<28} dtype={str(df[c].dtype):<8} non-nan={n_nonan:>6}")
