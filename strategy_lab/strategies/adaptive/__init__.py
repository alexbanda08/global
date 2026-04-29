"""
Adaptive regime-aware strategies (Phase 4).

Each module exposes `generate_signals(df, **params) -> dict`, returning the
dict contract expected by engine.run_backtest:
    {"entries": pd.Series[bool], "exits": pd.Series[bool],
     "short_entries": None, "short_exits": None,
     optional: "entry_limit_offset": pd.Series[float]}

Long-only V1; shorts land in V2 once limit-mode shorts ship in Phase 0.5d.
"""
from .a1_regime_switcher import generate_signals as a1_generate_signals
from .b1_kama_adaptive_trend import generate_signals as b1_generate_signals
from .c1_meta_labeled_donchian import generate_signals as c1_generate_signals
from .d1_htf_regime_ltf_pullback import generate_signals as d1_generate_signals

__all__ = ["a1_generate_signals", "b1_generate_signals",
           "c1_generate_signals", "d1_generate_signals"]
