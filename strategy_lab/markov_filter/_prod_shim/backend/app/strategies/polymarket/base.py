"""PolymarketBinaryStrategy — ABC for binary market strategies (Phase 18.1).

Phase 18.1 replaces the Phase 15 placeholder stubs with the validated
``sig_ret5m`` Binance-latency-arbitrage signal. The abstract ``signal()`` is
extended with an optional ``aux`` dict carrying pre-fetched Binance closes
and the timeframe-specific sniper threshold (computed by the controller).

Shared between ``Updown5mStrategy`` and ``Updown15mStrategy`` — both consume
the same ``aux["ret_5m"]`` and ``aux["abs_ret_5m_threshold"]`` regardless of
timeframe. The timeframe-specific quantile (q90 on 5m, q80 on 15m) is enforced
UPSTREAM by the controller via ``aux["abs_ret_5m_threshold"]``; the strategy
is timeframe-agnostic.

INVARIANTS:
- signal() is a PURE function: no IO, no time.time(), no mutation of bars/aux.
- Only CLOSED bars must be passed by the caller (CLAUDE.md invariant #4).
- No imports from engine.*, venues.polymarket.client, DB, or network.
- If ``aux`` is None or has missing/non-finite required keys, return "NONE".
  Strategy must NEVER crash on malformed aux.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar

SignalResult = Literal["UP", "DOWN", "NONE"]

# Phase 18.1: SignalConfig is reserved for future per-strategy config wiring
# (e.g. sleeve-specific overrides). Currently a structural placeholder; the
# strategy bodies do not read from it. Kept in the signature per RESEARCH §3.1
# for forward compatibility with the v0.2 controller refactor.
SignalConfig = Any


class PolymarketBinaryStrategy(ABC):
    """ABC for Polymarket binary updown strategies.

    Concrete subclasses bind their mode (``volume`` | ``sniper``) at
    ``__init__`` time. The ``signal`` method is pure: no IO, no time reads,
    no mutation.

    Usage::

        strategy = Updown5mStrategy(mode="volume")
        aux = {
            "binance_close_at_ws":     Decimal("60000"),
            "binance_close_5m_before": Decimal("59940"),
            "ret_5m":                  0.001,
            "abs_ret_5m_threshold":    None,
        }
        result = strategy.signal(closed_bars, config=None, aux=aux)
        # → "UP" | "DOWN" | "NONE"
    """

    @abstractmethod
    def signal(
        self,
        bars: list[Bar],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        """Compute direction signal from CLOSED bars and pre-fetched aux data.

        Args:
            bars: Closed Polymarket-side bars ordered oldest-first. Kept for
                  signature compatibility with Phase 15; the sig_ret5m signal
                  does not read from these bars (the relevant signal data
                  arrives via ``aux``). The controller still enforces all
                  bars are closed (CLAUDE.md invariant #4).
            config: Reserved for future per-strategy config injection. The
                  current sig_ret5m bodies do not read from it.
            aux: Optional dict carrying pre-fetched Binance closes and the
                  timeframe-specific sniper threshold. Expected schema::

                      aux = {
                          "binance_close_at_ws":     Decimal | None,  # close at window_start
                          "binance_close_5m_before": Decimal | None,  # close at window_start - 300s
                          "ret_5m":                  float | None,    # log(close_at_ws / close_5m_before)
                          "abs_ret_5m_threshold":    float | None,    # q90 if tf==5m else q80 (rolling 14d)
                      }

                  If ``aux`` is ``None`` or required keys are missing/non-finite,
                  ``signal()`` MUST return ``"NONE"`` and never crash.

        Returns:
            ``"UP"`` if the strategy says go long the YES side at this bar's
            window_start, ``"DOWN"`` if go long the NO side, ``"NONE"``
            otherwise (insufficient data, sniper-below-threshold, or
            ret_5m == 0 / non-finite).
        """


__all__ = ["PolymarketBinaryStrategy", "SignalConfig", "SignalResult"]
