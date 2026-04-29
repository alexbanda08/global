"""
Hurst voter — rolling Hurst exponent (R/S estimator).

Produces a trend-persistence confirmation: boosts the ADX+EMA trend vote
by 1.0 when H ≥ hurst_trend_threshold, attenuates by 1.0 when H ≤
hurst_revert_threshold. Sign is borrowed from the ADX+EMA slope direction
(computed inside vote() from features.ema_slope).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import VoterOutput


def _hurst_rs(series: np.ndarray, min_chunk: int = 8) -> float:
    """
    Rescaled-range Hurst estimator. Given a 1D array, return the Hurst
    exponent in [0, 1]. NaN-safe: callers should pass clean data.
    """
    n = len(series)
    if n < min_chunk * 2:
        return np.nan
    y = series - series.mean()
    Z = np.cumsum(y)
    R = Z.max() - Z.min()
    S = series.std(ddof=0)
    if S == 0:
        return np.nan
    rs_full = R / S

    # Two-scale estimate: compare R/S at full length vs half-length halves
    mid = n // 2
    h1 = series[:mid]; h2 = series[mid:]
    def _rs(x):
        m = x.mean(); yy = np.cumsum(x - m)
        s = x.std(ddof=0)
        return (yy.max() - yy.min()) / s if s > 0 else np.nan
    rs_half = np.nanmean([_rs(h1), _rs(h2)])
    if not np.isfinite(rs_half) or rs_half <= 0:
        return np.nan
    # H = log(rs_full / rs_half) / log(n/(n/2)) = log(rs_full / rs_half) / log(2)
    return float(np.log(rs_full / rs_half) / np.log(2.0))


class HurstVoter:
    name = "hurst"

    def vote(self, df, features, config) -> VoterOutput:
        close = df["close"]
        logret = np.log(close).diff().fillna(0.0).to_numpy()

        w = int(config.hurst_window)
        n = len(logret)
        h = np.full(n, np.nan)
        for i in range(w, n):
            h[i] = _hurst_rs(logret[i - w:i])

        h_series = pd.Series(h, index=df.index)
        # Boost: +1 when trending (H >= trend_threshold), -1 when mean-reverting
        #        (H <= revert_threshold). Else 0. Sign borrows from ema_slope.
        slope_sign = np.sign(features["ema_slope"].fillna(0.0))
        trending = (h_series >= config.hurst_trend_threshold).astype(float)
        reverting = (h_series <= config.hurst_revert_threshold).astype(float)
        vote = slope_sign * (trending - reverting)  # ∈ {-1, 0, +1}
        vote = vote.fillna(0.0)

        return VoterOutput(trend_vote=vote, vol_probs=None,
                           meta={"hurst_mean": float(h_series.mean(skipna=True))})
