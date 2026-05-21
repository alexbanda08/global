"""TRIGGER layer — entry catalysts (liquidation magnets, fair value gaps,
order-flow imbalance spikes).

Produces (per slug x outcome x window_start_unix):
  - trig_liq_magnet_active        (bool)
  - trig_liq_magnet_distance_bps  (float, NaN if not active)
  - trig_fvg_active               (bool)
  - trig_fvg_side                 (string: 'up' | 'down' | None)
  - trig_ofi_30s                  (float, normalized OFI in [-1, +1])
  - trigger_active                (bool composite — any catalyst aligned w/ side)

Strict no-lookahead: every feature at query_ts = ws_unix + 120s uses ONLY data
with ts <= query_ts (the entry-decision time for the momo sleeve).

Status: Phase 4 (built 2026-05-07).

See:
- strategy_lab/reports/CONFLUENCE_BUILD_PLAN_2026_05_07.md §Phase 4
- strategy_lab/confluence/schema.py TRIGGER_FEATURE_COLS
"""
from strategy_lab.confluence.trigger.liq_magnet import (  # noqa: F401
    compute_liq_magnet,
    LIQ_RADIUS_USD,
)
from strategy_lab.confluence.trigger.fvg import (  # noqa: F401
    compute_fvg,
)
from strategy_lab.confluence.trigger.ofi import (  # noqa: F401
    compute_ofi_30s,
)
