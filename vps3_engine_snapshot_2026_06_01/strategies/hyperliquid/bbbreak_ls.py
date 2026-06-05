"""SOL_BBBreak long/short strategy (Phase 7, Task 3 · STRAT-HL-01).

Bollinger-band breakout on closed bars. Ported from Fullproject
``sig_bbbreak_ls`` per 07-CONTEXT D-03; Fullproject source is external to
this worktree, so this implementation is a clean-room port from the BB+ATR
recipe documented in IMPLEMENTATION_GUIDE §4.1.

Invariants:

* Pure function of (``bars``, ``self.config``) — no IO, no global state.
* ``bars`` assumed oldest-first. Callers supplying desc order MUST reverse.
* BB is computed on ``bars[:-1]`` (closed prior window); breakout is
  evaluated on ``bars[-1].close`` vs the upper/lower band of the prior
  window — the upper/lower band does NOT include the signal bar itself.
  This is the STRAT-HL-09 no-look-ahead guard expressed at the algorithm
  level (the broader guard is Phase 4's closed-bar gate + the no-lookahead
  hypothesis test in Task 4).
* Sizing: ``size_by_atr`` + ``apply_notional_cap`` enforce the $10 notional
  cap at the strategy layer. ``PositionExecutor`` repeats the assertion
  (Task 6) for defense-in-depth.

CLAUDE.md invariants honored:

* #4 — strategy receives only closed bars (no ``bar_open + tf > now`` bar).
* #3 — 5s post-boundary buffer is enforced by ``get_bars()`` + BarEngine.

The ``cooldown_bars`` / ``cooldown_td`` is carried through to ``EntrySignal``
but NOT evaluated here — the sleeve controller decides whether to call
``evaluate`` at all based on the last exit time. D-03 says the strategy always
returns a signal when breakout conditions are met; cooldown gating is a
controller concern.
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
    bollinger_bands,
    size_by_atr,
)

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar
    from backend.app.strategies.hyperliquid.bbbreak_config import BBBreakConfig


# 4h bars → 4 hours per bar. Used for ``max_hold_td`` / ``cooldown_td``.
_TF_HOURS: dict[str, int] = {
    "4h": 4,
    "1h": 1,
    "15m": 0,  # 0 hours; handled in _tf_to_td
    "5m": 0,
    "1w": 24 * 7,
}


def _tf_to_td(tf: str, bars: int) -> timedelta:
    """Translate ``(tf, bars)`` into a ``timedelta``.

    Only the timeframes supported by ``BBBreakConfig`` need to round-trip
    here — 4h is the production default; 1h / 15m / 5m are included for
    future re-use.
    """
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
    raise ValueError(f"unsupported timeframe for BBBreak: {tf!r}")


class BBBreakStrategy(Strategy):
    """Bollinger-band breakout long/short.

    The concrete strategy class satisfies the controller's ``Strategy``
    Protocol: ``evaluate(bars)`` returns ``EntrySignal | None``. Config is
    bound at ``__init__`` and held on ``self``.
    """

    def __init__(self, config: BBBreakConfig) -> None:
        self.config = config

    def evaluate(self, bars: list[Bar]) -> EntrySignal | None:
        """Inspect ``bars`` (oldest-first); return a signal or ``None``.

        Algorithm:

        1. Require at least ``max(bb_period, atr_period) + breakout_confirm_bars``
           closed bars.
        2. Compute ATR on the full window.
        3. Compute BB on ``bars[:-1]`` (exclude the last closed bar — the
           bar we are evaluating the breakout ON must not participate in
           its own BB).
        4. If ``bars[-1].close > upper`` → long. If < ``lower`` → short.
        5. Size by ATR, then clamp by the notional cap.
        6. Build SL / TP at ``close ∓ atr_sl_mult × atr`` / ``close ± atr_tp_mult × atr``.
        """
        cfg = self.config

        min_required = max(cfg.bb_period, cfg.atr_period) + cfg.breakout_confirm_bars
        if len(bars) < min_required + 1:
            # Need one extra bar because BB is computed on `bars[:-1]` and
            # ATR needs `period+1` bars (leading close for the first TR).
            return None

        # ATR on the full window — ATR needs period+1 bars for TR.
        atr_px = atr(bars, cfg.atr_period)
        if atr_px <= 0:
            return None

        # BB on bars[:-1] — the candidate signal bar is NOT in the window.
        prior_window = bars[:-1]
        if len(prior_window) < cfg.bb_period:
            return None
        lower, _mid, upper = bollinger_bands(prior_window, cfg.bb_period, cfg.bb_std)

        close_px = bars[-1].close
        side: str | None = None
        if close_px > upper:
            side = "long"
        elif close_px < lower:
            side = "short"
        else:
            return None

        # Sizing. risk_per_trade_pct is a whole percent (1.0 = 1%), so
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


__all__ = ["BBBreakStrategy"]
