"""
strategy_lab.regime — 6-label regime classifier (Phase 2).

Public surface:
    classify_regime(df, config=REGIME_4H_PRESET)  -> pd.DataFrame
    RegimeConfig                                   # dataclass
    REGIME_4H_PRESET, REGIME_1H_PRESET, REGIME_15M_PRESET   # presets

The 6 labels are:
    strong_uptrend, weak_uptrend,
    sideways_low_vol, sideways_high_vol,
    weak_downtrend, strong_downtrend.

Design locked in docs/research/02_REGIME_LAYER.md.
"""
from __future__ import annotations

__all__ = [
    "classify_regime",
    "RegimeConfig",
    "REGIME_4H_PRESET",
    "REGIME_1H_PRESET",
    "REGIME_15M_PRESET",
    "REGIME_LABELS",
]

REGIME_LABELS = (
    "strong_uptrend",
    "weak_uptrend",
    "sideways_low_vol",
    "sideways_high_vol",
    "weak_downtrend",
    "strong_downtrend",
)

# The actual imports land once regime_classifier.py and config.py are written.
# Until then, this module just exports the label tuple for use by consumers
# writing placeholder strategies.
try:
    from .config import RegimeConfig, REGIME_4H_PRESET, REGIME_1H_PRESET, REGIME_15M_PRESET  # noqa: F401
    from .regime_classifier import classify_regime  # noqa: F401
except ImportError:
    # Implementation not yet shipped — don't break the import graph for the rest
    # of strategy_lab during Phase 2 development.
    pass
