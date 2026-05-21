"""FLOW layer — orderbook + trade-flow microstructure features.

Feeds `flow_score` and `flow_*` columns into the confluence classifier.

Status: Phase 1 (in build).
"""
from strategy_lab.confluence.flow.features import (  # noqa: F401
    compute_book_features,
    compute_trade_features,
    compute_flow_score,
    compute_all_for_slug_side,
)
