"""
classify_regime — orchestrator.

1. Builds the shared feature frame (features.feature_frame).
2. Instantiates every voter listed in config.voters.
3. Aggregates their outputs into (trend_score, vol_state) per bar.
4. Maps (trend_score, vol_state) → one of the 6 regime labels.
5. Applies trailing-only hysteresis (N-bar confirmation + hold floor +
   confidence-gated category switching).
6. Returns a DataFrame aligned with df.index, columns:
     label, confidence, trend_score, vol_state, change_pt.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import REGIME_LABELS
from .config import RegimeConfig, REGIME_4H_PRESET
from .features import feature_frame
from .voters import VOTER_REGISTRY


# Categories for the confidence-gated category switch
_TREND_CATEGORY = {
    "strong_uptrend":    "up",
    "weak_uptrend":      "up",
    "sideways_low_vol":  "side",
    "sideways_high_vol": "side",
    "weak_downtrend":    "down",
    "strong_downtrend":  "down",
}


def _label_from_score_and_vol(trend_score: float, vol_state: str) -> str:
    """
    Lookup-table implementation of § 1 of the design doc.

    Trend score dominates: |score|>=2 is strong, >=1 is weak, <1 is sideways.
    Vol only splits the sideways band. This is semantically cleaner than the
    earlier "promote weak-trend-high-vol to sideways" rule, which mislabeled
    high-vol bull rallies as sideways.
    """
    if trend_score >= 2.0:
        return "strong_uptrend"
    if trend_score <= -2.0:
        return "strong_downtrend"
    if trend_score >= 1.0:
        return "weak_uptrend"
    if trend_score <= -1.0:
        return "weak_downtrend"
    # |trend_score| < 1 → sideways; vol splits the bucket.
    if vol_state == "high":
        return "sideways_high_vol"
    return "sideways_low_vol"


def _apply_hysteresis(
    raw_labels: pd.Series,
    confidence: pd.Series,
    n_confirm: int,
    n_hold_floor: int,
    min_conf_for_category: float,
) -> pd.Series:
    """
    Trailing-only smoothing:
      * N_confirm: a new raw label becomes active only after n_confirm consecutive bars.
      * N_hold_floor: once active, cannot switch for another n_hold_floor bars.
      * Category switch gate: changes that cross {up, side, down} require
        confidence >= min_conf_for_category.
    """
    out = raw_labels.copy()
    current = raw_labels.iloc[0] if len(raw_labels) else None
    run = 1
    bars_since_switch = n_hold_floor  # initial state — allow first switch
    pending: str | None = None

    for i in range(len(raw_labels)):
        candidate = raw_labels.iloc[i]
        if candidate == current:
            run = 0
            pending = None
        else:
            if pending == candidate:
                run += 1
            else:
                pending = candidate
                run = 1

        allow_switch = False
        if pending is not None and run >= n_confirm and bars_since_switch >= n_hold_floor:
            # Category-crossing check
            cur_cat = _TREND_CATEGORY.get(current, "side")
            new_cat = _TREND_CATEGORY.get(pending, "side")
            if cur_cat == new_cat:
                allow_switch = True
            elif confidence.iloc[i] >= min_conf_for_category:
                allow_switch = True

        if allow_switch:
            current = pending
            pending = None
            run = 0
            bars_since_switch = 0
        else:
            bars_since_switch += 1

        out.iloc[i] = current
    return out


def classify_regime(
    df: pd.DataFrame,
    config: RegimeConfig = REGIME_4H_PRESET,
) -> pd.DataFrame:
    """
    See docs/research/02_REGIME_LAYER.md § 1 for the output contract.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df must have a pandas DatetimeIndex")
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"df missing required columns: {sorted(missing)}")

    # Step 1: build features
    features = feature_frame(
        df,
        vol_window=config.vol_window,
        trend_fast=config.ema_slope_fast,
        trend_slow=config.ema_slope_slow,
        adx_period=config.adx_period,
    )

    # Step 2: run voters
    trend_votes: list[tuple[float, pd.Series]] = []
    vol_prob_stacks: list[tuple[float, pd.DataFrame]] = []
    for voter_name in config.voters:
        if voter_name not in VOTER_REGISTRY:
            raise KeyError(
                f"Unknown voter {voter_name!r}. Known: {list(VOTER_REGISTRY)}"
            )
        voter = VOTER_REGISTRY[voter_name]()
        out = voter.vote(df, features, config)
        if out.trend_vote is not None:
            w = float(config.trend_weights.get(voter_name, 0.0))
            if w > 0:
                trend_votes.append((w, out.trend_vote.reindex(df.index).fillna(0.0)))
        if out.vol_probs is not None:
            w = float(config.vol_weights.get(voter_name, 0.0))
            if w > 0:
                vol_prob_stacks.append((w, out.vol_probs.reindex(df.index).fillna(0.0)))

    # Step 3: aggregate trend_score
    if trend_votes:
        trend_score = sum(w * v for w, v in trend_votes)
        max_trend = sum(w * 2.0 for w, _ in trend_votes)   # per voter in [-2,+2]
    else:
        trend_score = pd.Series(0.0, index=df.index)
        max_trend = 1.0
    trend_score = trend_score.clip(lower=-3.0, upper=3.0)

    # Step 4: aggregate vol probabilities
    if vol_prob_stacks:
        tot_w = sum(w for w, _ in vol_prob_stacks)
        vol_agg = sum((w / tot_w) * vp for w, vp in vol_prob_stacks)
    else:
        vol_agg = pd.DataFrame(
            {"low": 0, "normal": 1.0, "high": 0}, index=df.index,
        )
    vol_state = vol_agg.idxmax(axis=1)

    # Step 5: raw labels
    raw_labels = pd.Series([
        _label_from_score_and_vol(ts, vs)
        for ts, vs in zip(trend_score.values, vol_state.values)
    ], index=df.index, dtype="object")

    confidence = (trend_score.abs() / 3.0).clip(lower=0.0, upper=1.0)
    # If sideways and vol voters agree strongly, borrow some confidence from them
    side_mask = confidence < 0.4
    if side_mask.any():
        vol_agreement = vol_agg.max(axis=1)  # how concentrated is vol posterior
        confidence.loc[side_mask] = np.maximum(
            confidence.loc[side_mask], 0.4 * vol_agreement.loc[side_mask]
        )

    # Step 6: warmup override
    warm = min(config.warmup_bars, len(df))
    raw_labels.iloc[:warm] = config.neutral_label
    confidence.iloc[:warm] = 0.0

    # Step 7: hysteresis
    labels = _apply_hysteresis(
        raw_labels, confidence,
        n_confirm=config.n_confirm_bars,
        n_hold_floor=config.n_hold_floor_bars,
        min_conf_for_category=config.category_switch_min_confidence,
    )

    change_pt = labels.ne(labels.shift(1)).fillna(False)

    out = pd.DataFrame({
        "label":       pd.Categorical(labels, categories=list(REGIME_LABELS), ordered=False),
        "confidence":  confidence,
        "trend_score": trend_score,
        "vol_state":   pd.Categorical(vol_state, categories=["low","normal","high"], ordered=True),
        "change_pt":   change_pt,
    }, index=df.index)
    return out
