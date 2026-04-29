"""
Vol voter: expanding-window realized-vol quantile.

Produces a (low, normal, high) categorical DataFrame of indicators per bar.
Since the feature is already discrete, the output 'probability' frame is
one-hot (per row sums to 1, exactly one 1.0 entry).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import VoterOutput


class VolQuantileVoter:
    name = "vol_quantile"

    def vote(self, df, features, config) -> VoterOutput:
        state = features["vol_state"]  # Categorical: low / normal / high
        idx = df.index
        probs = pd.DataFrame(
            0.0, index=idx, columns=["low", "normal", "high"],
        )
        probs.loc[state == "low",    "low"]    = 1.0
        probs.loc[state == "normal", "normal"] = 1.0
        probs.loc[state == "high",   "high"]   = 1.0
        # Any remaining rows (NaN state) default to normal = 1.
        unassigned = probs.sum(axis=1) == 0.0
        probs.loc[unassigned, "normal"] = 1.0
        return VoterOutput(trend_vote=None, vol_probs=probs)
