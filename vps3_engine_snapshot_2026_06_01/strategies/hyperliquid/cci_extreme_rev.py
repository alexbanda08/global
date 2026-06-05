"""ETH CCI Extreme Reversal strategy (Phase 8, Task 4 · STRAT-HL-03).

Clean-room port per 08-CONTEXT D-04 — Fullproject source is external.

Algorithm:

* Compute CCI(cci_period) on the full window of closed bars.
* If ``cci < -cci_extreme_threshold`` → LONG (oversold reversal).
* If ``cci > +cci_extreme_threshold`` → SHORT (overbought reversal).
* Else ``None``.
* On signal: size by ATR, clamp by notional cap, build SL / TP.

Invariants:

* Pure function — no IO imports from ``backend.app.(venues|db|executors|engine|controllers)``.
* ``bars`` assumed oldest-first.
* Tighter TP and shorter max_hold than BBBreak — reversal edge is thinner.
* ATR SL is WIDER than BBBreak (2.5 vs 2.0) — counter-trend entries need
  room to breathe through the noise at the reversal point.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from backend.app.strategies.base import (
    EntrySignal,
    Strategy,
    apply_notional_cap,
    atr,
    cci,
    size_by_atr,
)

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar
    from backend.app.strategies.hyperliquid.cci_extreme_rev_config import (
        CCIExtremeRevConfig,
    )


def _tf_to_td(tf: str, bars: int) -> timedelta:
    """Translate ``(tf, bars)`` into a ``timedelta`` — duplicated from sibling strategies."""
    if tf == "4h":
        return timedelta(hours=4 * bars)
    if tf == "1h":
        return timedelta(hours=bars)
    if tf == "15m":
        return timedelta(minutes=15 * bars)
    if tf == "5m":
        return timedelta(minutes=5 * bars)
    if tf == "1w":
        return timedelta(weeks=bars)
    raise ValueError(f"unsupported timeframe for CCIExtremeRev: {tf!r}")


class CCIExtremeRevStrategy(Strategy):
    """CCI extreme reversal strategy.

    Config bound at ``__init__`` — matches the ``Strategy`` Protocol expected
    by ``HyperliquidSleeveController``.
    """

    def __init__(self, config: CCIExtremeRevConfig) -> None:
        self.config = config

    def evaluate(self, bars: list[Bar]) -> EntrySignal | None:
        """Return an ``EntrySignal`` on CCI extreme, else ``None``.

        Algorithm:

        1. Require ``len(bars) >= max(cci_period, atr_period + 1)``.
        2. Compute ATR + CCI.
        3. If CCI < -threshold → long (oversold reversal).
           If CCI > +threshold → short (overbought reversal).
        4. Size / clamp / build SL + TP.
        """
        cfg = self.config
        min_required = max(cfg.cci_period, cfg.atr_period + 1)
        if len(bars) < min_required:
            return None

        atr_px = atr(bars, cfg.atr_period)
        if atr_px <= 0:
            return None

        cci_val = cci(bars, cfg.cci_period)

        side: str | None = None
        if cci_val < -cfg.cci_extreme_threshold:
            side = "long"
        elif cci_val > cfg.cci_extreme_threshold:
            side = "short"
        else:
            return None

        close_px = bars[-1].close

        # Sizing: risk_per_trade_pct is a whole percent (1.0 = 1%), so
        # normalize to a fraction before feeding size_by_atr.
        risk_fraction = cfg.risk_per_trade_pct / Decimal("100")
        raw_qty = size_by_atr(
            equity=cfg.equity_usd,
            atr_px=atr_px,
            risk_per_trade_pct=risk_fraction,
            atr_sl_mult=cfg.atr_sl_mult,
        )
        qty = apply_notional_cap(raw_qty, close_px, cfg.notional_cap_usd)
        if qty <= 0:
            return None

        # SL / TP barriers.
        if side == "long":
            sl_px = close_px - cfg.atr_sl_mult * atr_px
            tp_px = close_px + cfg.atr_tp_mult * atr_px
        else:  # short
            sl_px = close_px + cfg.atr_sl_mult * atr_px
            tp_px = close_px - cfg.atr_tp_mult * atr_px

        return EntrySignal(
            symbol=cfg.symbol,
            side=side,  # type: ignore[arg-type]
            qty=qty,
            limit_px=close_px,
            sl_px=sl_px,
            tp_px=tp_px,
            atr_px=atr_px,
            max_hold_td=_tf_to_td(cfg.timeframe, cfg.max_hold_bars),
            cooldown_td=_tf_to_td(cfg.timeframe, cfg.cooldown_bars),
        )


__all__ = ["CCIExtremeRevStrategy"]
