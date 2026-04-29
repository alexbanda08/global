"""
Voter protocol and shared types.

A voter takes (df, features, config) and returns a VoterOutput containing:
  - trend_vote: signed series in roughly [-2, +2] (or None if voter doesn't vote trend)
  - vol_probs : DataFrame [low, normal, high] summing to 1 per row (or None)
  - meta      : dict with any voter-specific diagnostics (e.g. HMM state id)

All computations must be trailing-only. NaN warmup bars are OK; the orchestrator
handles them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd


@dataclass
class VoterOutput:
    trend_vote: pd.Series | None = None
    vol_probs:  pd.DataFrame | None = None
    meta:       dict = field(default_factory=dict)


class Voter(Protocol):
    """
    Structural typing — any class exposing .name and .vote(...) matches.
    """
    name: str

    def vote(
        self,
        df: pd.DataFrame,
        features: pd.DataFrame,
        config: "RegimeConfig",      # noqa: F821  (forward ref)
    ) -> VoterOutput: ...
