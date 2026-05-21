"""Schema contracts for the Multi-Layer Confluence System.

Defines the column names and types each layer must produce, plus the tier
classifier output dict shape. Single source of truth — every module in
strategy_lab/confluence/ imports from here so changes propagate cleanly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

# ---------------------------------------------------------------------------
# Universal constants
# ---------------------------------------------------------------------------

BANKROLL_DEFAULT = 1250.0   # per-sleeve bankroll for size_pct calc
                            # = 50 sleeves × $25 baseline; tune in Phase 5

# ---------------------------------------------------------------------------
# Feature column contracts (per (slug, ws_unix) row in enriched universe)
# ---------------------------------------------------------------------------

# FLOW features — Phase 1 (computed at ws_unix + 120s, the entry decision time)
FLOW_FEATURE_COLS: tuple[str, ...] = (
    "flow_cvd_1m",
    "flow_cvd_5m",
    "flow_aggressor_ratio_30s",
    "flow_imb_l1",
    "flow_imb_l5",
    "flow_imb_l10",
    "flow_imb_l25",
    "flow_bid_max_size_l10_usd",
    "flow_depth_l5_usd",
    "flow_depth_l10_usd",
    "flow_depth_l25_usd",
    "flow_momentum_30s",
    "flow_score",            # composite [-1, +1]
)

# STRUCTURE features — Phase 3
STRUCTURE_FEATURE_COLS: tuple[str, ...] = (
    "struct_btc_trend_1h_slope",
    "struct_btc_trend_4h_slope",
    "struct_dist_to_resistance_bps",
    "struct_dist_to_support_bps",
    "struct_regime",          # "trend" / "sideways" / "volatile"
    "struct_score",           # composite [-1, +1]
)

# TRIGGER features — Phase 4
TRIGGER_FEATURE_COLS: tuple[str, ...] = (
    "trig_liq_magnet_active",
    "trig_liq_magnet_distance_bps",
    "trig_fvg_active",
    "trig_fvg_side",          # "up" / "down" / null
    "trig_ofi_30s",
    "trigger_active",         # bool — composite trigger fire flag
)

# GUARD blocks — Phase 2 (each is a bool; True = block this trade)
GUARD_BLOCK_COLS: tuple[str, ...] = (
    "guard_extreme_price",       # entry_price < 0.35 or > 0.65
    "guard_dead_market",         # t<90s post-open AND |btc_move|<$5
    "guard_counter_trend",       # continuation move (block — see anti-edge)
    "guard_min_time_to_close",   # remaining time < 1m
    "guard_choppiness",          # chop_index_5m > 0.70
)

ALL_FEATURE_COLS: tuple[str, ...] = (
    FLOW_FEATURE_COLS + STRUCTURE_FEATURE_COLS + TRIGGER_FEATURE_COLS + GUARD_BLOCK_COLS
)


# ---------------------------------------------------------------------------
# Tier classifier output
# ---------------------------------------------------------------------------

Tier = Literal["GOLD", "SILVER", "BRONZE", "SKIP"]


class TierResult(TypedDict):
    tier: Tier
    fair_prob: float | None    # estimated win probability (None for SKIP)
    size_pct: float            # fraction of bankroll [0, 0.020]
    skip_reasons: tuple[str, ...]  # populated when tier == "SKIP"


SKIP: TierResult = {
    "tier": "SKIP",
    "fair_prob": None,
    "size_pct": 0.0,
    "skip_reasons": (),
}


# ---------------------------------------------------------------------------
# Bucket grain
# ---------------------------------------------------------------------------

BUCKET_SECS_DEFAULT = 10   # FLOW features computed per 10s bucket;
                           # downgrade to 5s in Phase 1 if signal fades.


# ---------------------------------------------------------------------------
# Universe row contract — what `feature_join.enrich_universe()` MUST add
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UniverseContract:
    """The columns the backtest engine needs after confluence enrichment.

    Existing columns from `load_universe()` (kept untouched):
      slug, asset, timeframe, window_start_unix, outcome_up, asset_ret_2m, signal

    Added by enrich_universe():
      All of ALL_FEATURE_COLS above (NaN-filled when source data missing).
      Plus: tier, fair_prob, size_pct, skip_reasons (set by tier_classifier).
    """
    required_input_cols: tuple[str, ...] = (
        "slug", "asset", "timeframe", "window_start_unix", "outcome_up",
    )
    added_feature_cols: tuple[str, ...] = ALL_FEATURE_COLS
    added_tier_cols: tuple[str, ...] = (
        "tier", "fair_prob", "size_pct", "skip_reasons",
    )


CONTRACT = UniverseContract()
