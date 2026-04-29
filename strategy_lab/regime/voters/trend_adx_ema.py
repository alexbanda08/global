"""
Trend voter: ADX magnitude + EMA-slope sign.

Vote mapping:
  adx >= strong_threshold  (default 25)
  AND |ema_slope| >= strong_pct (default 0.02):
      +2 if slope > 0
      -2 if slope < 0
  adx >= weak_threshold (default 20)   ⇒ ±1 depending on slope sign
  adx <  weak_threshold                ⇒ 0

Shipping as its own voter keeps the trend score interpretable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import VoterOutput


class TrendAdxEmaVoter:
    name = "trend_adx_ema"

    def vote(self, df, features, config) -> VoterOutput:
        adx = features["adx"]
        slope = features["ema_slope"]

        strong = (adx >= config.adx_strong_threshold) & (slope.abs() >= config.ema_slope_strong_pct)
        # Weak requires BOTH adx >= weak_threshold AND |slope| >= weak slope floor.
        # Prevents ADX>20 + nearly-flat slope from ever being called a trend.
        weak = (
            (adx >= config.adx_weak_threshold)
            & (slope.abs() >= config.ema_slope_weak_pct)
            & ~strong
        )

        vote = pd.Series(0.0, index=df.index)
        vote[strong & (slope > 0)] = 2.0
        vote[strong & (slope < 0)] = -2.0
        vote[weak   & (slope > 0)] = 1.0
        vote[weak   & (slope < 0)] = -1.0
        vote = vote.where(~(adx.isna() | slope.isna()), 0.0)

        return VoterOutput(trend_vote=vote, vol_probs=None,
                           meta={"adx_mean": float(adx.mean(skipna=True))})
