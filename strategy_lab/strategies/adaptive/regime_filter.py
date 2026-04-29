"""
Regime-filter overlay — wraps ANY signal generator with a pre-filter that
zeroes entries outside user-specified regime labels. The wrapped strategy
still produces its exits unchanged, so positions opened before the regime
shifted are allowed to close normally.

Usage:
    from strategies.adaptive.regime_filter import with_regime_filter
    from strategies_v2 import gaussian_channel_v2

    filtered = with_regime_filter(
        gaussian_channel_v2,
        allowed_labels=("strong_uptrend", "weak_uptrend"),
    )
    sig = filtered(df)

Rationale: robustness battery revealed that both C1 ETH and
gaussian_channel_v2 BTC owe most of their P&L to the 2024 uptrend. A
regime gate formalises that intuition — trade only when the classifier
agrees we're in a favourable regime. This is a behavioural filter, not a
parameter retune.
"""
from __future__ import annotations

from typing import Callable, Iterable

import pandas as pd

from regime import classify_regime, REGIME_4H_PRESET


DEFAULT_UPTREND_LABELS = ("strong_uptrend", "weak_uptrend")


def with_regime_filter(
    signal_fn: Callable[..., dict | tuple],
    *,
    allowed_labels: Iterable[str] = DEFAULT_UPTREND_LABELS,
    min_confidence: float = 0.0,
    regime_config=REGIME_4H_PRESET,
    also_force_exit_on_leave: bool = True,
) -> Callable[..., dict]:
    """
    Returns a new generate_signals function that:
      * Classifies the regime on the passed df.
      * Builds an `in_regime` mask from (label in allowed_labels) AND
        (confidence >= min_confidence).
      * Calls the underlying signal_fn.
      * AND-masks `entries` with `in_regime`.
      * If `also_force_exit_on_leave`, OR-adds a regime-leave pulse
        (`~in_regime & in_regime.shift(1)`) into `exits` — existing
        positions close when regime flips out.

    Leaves short_entries/short_exits untouched.
    """
    allowed = tuple(allowed_labels)

    def _filtered(df: pd.DataFrame, **kwargs) -> dict:
        regime = classify_regime(df, config=regime_config)
        in_regime = (
            regime["label"].astype(str).isin(allowed)
            & (regime["confidence"] >= float(min_confidence))
        )

        out = signal_fn(df, **kwargs)
        if isinstance(out, tuple) and len(out) == 2:
            out = {"entries": out[0], "exits": out[1]}
        if not isinstance(out, dict):
            raise TypeError(f"signal_fn must return dict or tuple; got {type(out)}")

        entries = out.get("entries")
        exits = out.get("exits")
        if entries is None:
            return out
        entries = entries.reindex(df.index).fillna(False).astype(bool)
        entries = entries & in_regime.reindex(df.index).fillna(False)

        if also_force_exit_on_leave and exits is not None:
            exits = exits.reindex(df.index).fillna(False).astype(bool)
            leave = (~in_regime) & in_regime.shift(1).fillna(False)
            exits = exits | leave.reindex(df.index).fillna(False)
            out["exits"] = exits

        out["entries"] = entries
        meta = out.get("_meta", {}) if isinstance(out.get("_meta"), dict) else {}
        meta.update({
            "regime_filter": True,
            "allowed_labels": list(allowed),
            "min_confidence": float(min_confidence),
            "in_regime_pct": float(in_regime.mean()),
            "entries_pre_filter": int(out.get("_entries_pre_filter_count", 0)
                                      or entries.shape[0]),  # rough; best effort
            "entries_post_filter": int(entries.sum()),
        })
        out["_meta"] = meta
        return out

    _filtered.__name__ = f"regime_filtered_{getattr(signal_fn, '__name__', 'unknown')}"
    _filtered.__doc__ = f"regime-filtered wrapper around {signal_fn}"
    return _filtered
