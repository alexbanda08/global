"""Multi-Layer Confluence System (Cyclops-inspired).

Architecture: 4 independent confirmation layers (STRUCTURE / FLOW / TRIGGER / GUARD)
fed into a tier classifier (GOLD / SILVER / BRONZE / SKIP) that sets entry size.

See:
- strategy_lab/reports/CONFLUENCE_BUILD_PLAN_2026_05_07.md (build plan)
- strategy_lab/reports/TRADINGVENUE_VS_CYCLOPS_2026_05_06.md (source spec)

Phase 0 status: skeleton only. Layers populate in phases 1-4.
"""
__version__ = "0.0.1-skeleton"

from strategy_lab.confluence.schema import (  # noqa: F401
    TierResult,
    SKIP,
    BANKROLL_DEFAULT,
)
from strategy_lab.confluence.tier_classifier import classify  # noqa: F401
from strategy_lab.confluence.feature_join import enrich_universe  # noqa: F401
