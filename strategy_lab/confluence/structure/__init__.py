"""STRUCTURE layer — macro-context features for confluence classifier.

Produces (per slug × window_start_unix):
  - struct_btc_trend_1h_slope, struct_btc_trend_4h_slope
    (BTC kline regression slopes; macro driver even for ETH/SOL markets)
  - struct_dist_to_resistance_bps, struct_dist_to_support_bps
    (5-day swing-high/low levels on the asset's own klines)
  - struct_regime ('trend' | 'sideways' | 'volatile') with hysteresis
  - struct_score (composite [-1, +1], side-agnostic)

Strict no-lookahead: every feature at ws_unix uses ONLY data with ts <= ws_unix.

Status: Phase 3 (built 2026-05-07).

See:
- strategy_lab/reports/CONFLUENCE_BUILD_PLAN_2026_05_07.md §Phase 3
- strategy_lab/confluence/schema.py STRUCTURE_FEATURE_COLS
"""
from strategy_lab.confluence.structure.btc_trend import (  # noqa: F401
    rolling_slope_norm,
    compute_trend_slopes,
)
from strategy_lab.confluence.structure.sr_levels import (  # noqa: F401
    extract_swings,
    nearest_distance_bps,
)
from strategy_lab.confluence.structure.regime_classifier import (  # noqa: F401
    classify_regime_series,
)
