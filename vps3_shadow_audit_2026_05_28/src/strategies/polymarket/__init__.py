"""Polymarket binary strategies package (Phase 18.1, STRAT-BIN-01).

Exports:
- PolymarketBinaryStrategy — ABC with signal(bars, config, aux) -> "UP"|"DOWN"|"NONE"
- Updown5mStrategy  — sig_ret5m signal for 5m markets (mode=volume|sniper)
- Updown15mStrategy — sig_ret5m signal for 15m markets (mode=volume|sniper)
- MomoStrategy      — Phase 18.5 momentum signal at t+120s (per-momo-controller)

The 5m and 15m bodies are identical; the timeframe-specific sniper quantile
(q90 on 5m vs q80 on 15m) is enforced upstream by the controller via
``aux["abs_ret_5m_threshold"]``.

IMPORT SAFETY: this package has ZERO imports from engine.*, venues.polymarket.client,
DB, or network. Strategies are PURE functions.
"""
from __future__ import annotations

from backend.app.strategies.polymarket.base import PolymarketBinaryStrategy
from backend.app.strategies.polymarket.momo import MomoStrategy
from backend.app.strategies.polymarket.momo_v2 import MomoV2Strategy
from backend.app.strategies.polymarket.updown_5m import Updown5mStrategy
from backend.app.strategies.polymarket.updown_15m import Updown15mStrategy

__all__ = [
    "MomoStrategy",
    "MomoV2Strategy",
    "PolymarketBinaryStrategy",
    "Updown15mStrategy",
    "Updown5mStrategy",
]
