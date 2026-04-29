"""
V50 — New signal families from internet research (April 2026).

Each signal function returns (long_entries, short_entries) as pd.Series[bool].

1. sig_mfi_extreme         — Money Flow Index (volume-weighted RSI)
                              Enter long on 20-cross-up from oversold, short on 80-cross-down.
                              Research: stronger when paired with divergence; works on liquid assets.
2. sig_vwap_band_fade      — Rolling 100-bar VWAP with ±2σ bands.
                              Long when close touches -2σ AND VWAP slope flat; short on +2σ.
                              Research: works best in range-bound markets.
3. sig_volume_profile_rot  — Rolling 120-bar volume profile.
                              Compute POC (highest-volume price), VAH (70% value-area high),
                              VAL (70% value-area low). Long near VAL, short near VAH.
                              Research: range-bound edge via rotation back to POC.
4. sig_signed_vol_div      — Signed-volume divergence (CVD proxy).
                              price_signed_vol = volume * sign(close - open)
                              cum-sum over rolling window. Divergence: price makes new low
                              but cumulative signed-vol does not (or vice versa).
                              Research: CVD divergence widely used on perps.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


# ---------- helpers ----------
def _typical_price(df: pd.DataFrame) -> pd.Series:
    return (df["high"] + df["low"] + df["close"]) / 3


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift()
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n // 2).mean()


# =============================================================================
# 1. MFI Extreme — volume-weighted RSI with 80/20 bands
# =============================================================================
def sig_mfi_extreme(df: pd.DataFrame, n: int = 14,
                    lower: float = 20.0, upper: float = 80.0,
                    require_cross: bool = True) -> tuple[pd.Series, pd.Series]:
    """
    MFI = 100 - 100/(1 + money_ratio), where
      money_ratio = sum(positive raw_money) / sum(negative raw_money) over window n
      raw_money   = typical_price * volume
      positive if typical_price > prior typical_price, else negative.

    Long  when MFI crosses BACK ABOVE `lower` after being below (exit oversold).
    Short when MFI crosses BACK BELOW `upper` after being above (exit overbought).
    """
    tp = _typical_price(df)
    vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
    raw_money = tp * vol
    tp_change = tp.diff()
    pos_money = raw_money.where(tp_change > 0, 0.0)
    neg_money = raw_money.where(tp_change < 0, 0.0)
    pos_sum = pos_money.rolling(n, min_periods=n // 2).sum()
    neg_sum = neg_money.rolling(n, min_periods=n // 2).sum()
    money_ratio = pos_sum / neg_sum.replace(0, np.nan)
    mfi = 100 - 100 / (1 + money_ratio)

    prev = mfi.shift()
    if require_cross:
        long_entries = (prev < lower) & (mfi >= lower)
        short_entries = (prev > upper) & (mfi <= upper)
    else:
        long_entries = mfi < lower
        short_entries = mfi > upper
    return long_entries.fillna(False), short_entries.fillna(False)


# =============================================================================
# 2. VWAP Band Fade — rolling VWAP with ±2σ bands
# =============================================================================
def sig_vwap_band_fade(df: pd.DataFrame, n: int = 100,
                       sigma: float = 2.0, slope_win: int = 20,
                       slope_eps: float = 0.01) -> tuple[pd.Series, pd.Series]:
    """
    Rolling-window VWAP using typical-price-weighted volume.
    Bands = VWAP ± sigma * std_of_vwap_residuals over window n.
    Long  when low pierces lower band AND VWAP slope is flat (|slope| < eps).
    Short when high pierces upper band AND VWAP slope is flat.
    Slope measured as normalized delta (vwap_t - vwap_{t-slope_win}) / close.
    """
    tp = _typical_price(df)
    vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
    # rolling volume-weighted typical price
    pv = tp * vol
    vwap = pv.rolling(n, min_periods=n // 2).sum() / vol.rolling(n, min_periods=n // 2).sum().replace(0, np.nan)
    resid = tp - vwap
    sd = resid.rolling(n, min_periods=n // 2).std()
    upper = vwap + sigma * sd
    lower = vwap - sigma * sd
    slope = (vwap - vwap.shift(slope_win)) / df["close"]
    flat = slope.abs() < slope_eps

    long_entries = (df["low"] <= lower) & flat & (df["close"] > lower)  # wick down, close back above
    short_entries = (df["high"] >= upper) & flat & (df["close"] < upper)
    return long_entries.fillna(False), short_entries.fillna(False)


# =============================================================================
# 3. Volume Profile Rotation — POC/VAH/VAL on rolling window
# =============================================================================
def _rolling_volume_profile_levels(close: pd.Series, volume: pd.Series,
                                    win: int = 120, n_bins: int = 20,
                                    value_area: float = 0.70
                                    ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute rolling POC, VAH, VAL for each bar (point-in-time, no look-ahead)."""
    close_arr = close.to_numpy()
    vol_arr = volume.to_numpy()
    N = len(close)
    poc = np.full(N, np.nan); vah = np.full(N, np.nan); val = np.full(N, np.nan)

    for i in range(win, N):
        price_slice = close_arr[i-win:i]
        vol_slice = vol_arr[i-win:i]
        pmin, pmax = float(price_slice.min()), float(price_slice.max())
        if pmax <= pmin:
            continue
        edges = np.linspace(pmin, pmax, n_bins + 1)
        # bin each price; accumulate volume
        bin_idx = np.digitize(price_slice, edges) - 1
        bin_idx = np.clip(bin_idx, 0, n_bins - 1)
        vol_by_bin = np.zeros(n_bins)
        for j in range(len(price_slice)):
            vol_by_bin[bin_idx[j]] += vol_slice[j]
        if vol_by_bin.sum() == 0:
            continue
        poc_bin = int(vol_by_bin.argmax())
        poc[i] = (edges[poc_bin] + edges[poc_bin + 1]) / 2

        # expand value area outward from POC until reaching value_area * total
        total = vol_by_bin.sum()
        target = total * value_area
        include = np.zeros(n_bins, dtype=bool)
        include[poc_bin] = True
        cum = vol_by_bin[poc_bin]
        lo_idx = poc_bin; hi_idx = poc_bin
        while cum < target and (lo_idx > 0 or hi_idx < n_bins - 1):
            up = vol_by_bin[hi_idx + 1] if hi_idx + 1 < n_bins else -1
            dn = vol_by_bin[lo_idx - 1] if lo_idx - 1 >= 0 else -1
            if up >= dn and up >= 0:
                hi_idx += 1; include[hi_idx] = True; cum += vol_by_bin[hi_idx]
            elif dn >= 0:
                lo_idx -= 1; include[lo_idx] = True; cum += vol_by_bin[lo_idx]
            else:
                break
        vah[i] = edges[hi_idx + 1]
        val[i] = edges[lo_idx]

    return (pd.Series(poc, index=close.index),
            pd.Series(vah, index=close.index),
            pd.Series(val, index=close.index))


def sig_volume_profile_rot(df: pd.DataFrame,
                            win: int = 120, n_bins: int = 20,
                            touch_buffer: float = 0.001
                            ) -> tuple[pd.Series, pd.Series]:
    """
    Rolling volume profile; long when close within `touch_buffer` of VAL
    (touched from below, closed above), short near VAH.
    """
    close = df["close"]
    vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
    poc, vah, val = _rolling_volume_profile_levels(close, vol, win=win, n_bins=n_bins)

    # touch within buffer of VAL from below (wicked below, closed within buffer)
    near_val = (df["low"] <= val * (1 + touch_buffer)) & (close > val) & (close < poc)
    near_vah = (df["high"] >= vah * (1 - touch_buffer)) & (close < vah) & (close > poc)
    # require at least some value-area width (not degenerate profile)
    width_ok = (vah - val) / close > 0.005

    return (near_val & width_ok).fillna(False), (near_vah & width_ok).fillna(False)


# =============================================================================
# 4. Signed-Volume Divergence (CVD proxy)
# =============================================================================
def sig_signed_vol_div(df: pd.DataFrame, lookback: int = 20,
                       cvd_win: int = 50,
                       min_cvd_threshold: float = 0.2) -> tuple[pd.Series, pd.Series]:
    """
    CVD proxy: signed_vol = volume * sign(close - open)
    Rolling cumulative sum over `cvd_win`.
    Bullish divergence: price makes new `lookback`-bar low, but cvd > its
      rolling median by > min_cvd_threshold * std → hidden accumulation.
    Bearish divergence: price makes new lookback high, cvd < median - threshold.
    """
    close = df["close"]
    op = df["open"]
    vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
    signed_vol = vol * np.sign(close - op)
    cvd = signed_vol.rolling(cvd_win, min_periods=cvd_win // 2).sum()
    cvd_med = cvd.rolling(cvd_win*2, min_periods=cvd_win).median()
    cvd_sd = cvd.rolling(cvd_win*2, min_periods=cvd_win).std()

    price_low = close.rolling(lookback, min_periods=lookback // 2).min()
    price_high = close.rolling(lookback, min_periods=lookback // 2).max()
    at_new_low = close <= price_low * 1.001
    at_new_high = close >= price_high * 0.999

    # bullish div: new low + cvd above baseline
    bull = at_new_low & (cvd > cvd_med + min_cvd_threshold * cvd_sd)
    bear = at_new_high & (cvd < cvd_med - min_cvd_threshold * cvd_sd)
    return bull.fillna(False), bear.fillna(False)
