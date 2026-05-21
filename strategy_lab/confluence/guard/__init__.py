"""GUARD layer — filters that block trades on flagged conditions.

Phase 2 of CONFLUENCE_BUILD_PLAN_2026_05_07.md.

Each guard is a boolean column. classifier returns SKIP if ANY guard is True.
"""
from strategy_lab.confluence.guard.filters import (  # noqa: F401
    compute_extreme_price,
    compute_dead_market,
    compute_counter_trend,
    compute_min_time_to_close,
    compute_choppiness,
    compute_all_guards,
)
