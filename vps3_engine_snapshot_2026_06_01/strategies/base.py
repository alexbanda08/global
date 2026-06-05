"""Strategy ABC + shared pure helpers (Phase 7, Task 2 · STRAT-HL-05).

Per 07-CONTEXT D-04 this module is the backbone for every future Tradingvenue
strategy (DOGE_HTF_Donchian, ETH_CCI_Rev, V24 XSM, future binary sleeves):

* ``Strategy`` — ABC with ``evaluate(bars) -> EntrySignal | None``. Config
  is held on the concrete subclass (bound at ``__init__``) so the public
  ``evaluate`` signature matches the ``Strategy`` Protocol used by
  ``backend.app.controllers.base`` — the BarEngine / controller never
  passes a config object at dispatch time.
* ``EntrySignal`` — frozen Pydantic v2 model with all fields
  ``PositionExecutor.open_position`` consumes (symbol, side, qty, limit_px,
  sl_px, tp_px, atr_px, max_hold_td, cooldown_td).
* Pure helpers: ``atr``, ``bollinger_bands``, ``size_by_atr``,
  ``apply_notional_cap``, ``in_cooldown``. Zero IO, zero global state,
  zero imports from ``backend.app.{venues,db,executors,engine,controllers}``.

Invariants (CLAUDE.md #4 + STRAT-HL-09):

* Every helper consumes ``list[Bar]`` as strictly CLOSED bars; the no-peek
  property is tested via ``backend/tests/unit/test_bbbreak_no_lookahead.py``.
* ``Decimal`` throughout financial math — no ``float`` in sizing or price
  arithmetic. Phase-10 rails will enforce stricter numeric discipline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar


class EntrySignal(BaseModel):
    """Input to ``PositionExecutor.open_position``.

    Frozen so strategies can construct it once and hand it off without fear
    of downstream mutation. All numeric fields are ``Decimal`` — no ``float``
    leaks into the order path (PITFALLS row 3 mitigation).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    side: Literal["long", "short"]
    qty: Decimal
    limit_px: Decimal
    sl_px: Decimal
    tp_px: Decimal
    atr_px: Decimal
    max_hold_td: timedelta
    cooldown_td: timedelta


class Strategy(ABC):
    """Abstract strategy base. Concrete subclasses bind config at ``__init__``.

    The BarEngine (Phase 7) calls ``strategy.evaluate(bars)`` at each bar
    boundary; it does NOT pass a config. Per-strategy config (Bollinger
    period, ATR multiples, notional cap, …) therefore lives on ``self``
    and is set by the subclass constructor.

    Subclasses MUST:

    * accept an immutable config object in ``__init__`` and store it
      as ``self.config`` (by convention — not enforced).
    * implement ``evaluate(bars)`` as a pure function of ``bars`` + ``self.config``
      (no IO, no time reads except via an injectable clock, no mutation of
      ``bars``).
    """

    @abstractmethod
    def evaluate(self, bars: list[Bar]) -> EntrySignal | None:
        """Produce an entry signal for the given closed-bar window, or ``None``.

        ``bars`` is ordered newest-first or newest-last depending on caller —
        concrete strategies document their expected order. Phase 4's
        ``get_bars()`` returns newest-first (desc ``bar_open``); strategies
        commonly reverse internally.

        Returns ``None`` when no trade setup is present (the common case).
        """


# ---------------------------------------------------------------------------
# Pure helpers — deliberately simple, no IO, Decimal throughout.
# ---------------------------------------------------------------------------


def atr(bars: list[Bar], period: int = 14) -> Decimal:
    """Wilder's Average True Range over the last ``period`` bars.

    ``bars`` MUST be ordered oldest-first (chronological ascending). The
    caller is responsible for the ordering (Phase 4's ``get_bars`` returns
    desc, so strategy code typically reverses before calling).

    Wilder's smoothing (EMA with alpha = 1/period) is the canonical ATR
    recipe. For the first ``period`` TR values we use a simple mean to
    seed; subsequent TR values are blended as
    ``atr_t = (atr_{t-1} * (period-1) + tr_t) / period``.

    Raises
    ------
    ValueError
        If fewer than ``period + 1`` bars are supplied (ATR needs at least
        ``period`` TR values and TR needs the previous close).
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if len(bars) < period + 1:
        raise ValueError(
            f"need at least {period + 1} bars for ATR({period}), got {len(bars)}"
        )

    # True Range: max(high-low, |high - prev_close|, |low - prev_close|).
    trs: list[Decimal] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        hi = bars[i].high
        lo = bars[i].low
        tr = max(
            hi - lo,
            abs(hi - prev_close),
            abs(lo - prev_close),
        )
        trs.append(tr)

    period_dec = Decimal(period)
    # Seed: simple average of the first `period` TRs.
    seed = sum(trs[:period], Decimal("0")) / period_dec
    cur = seed
    # Wilder smoothing for the rest.
    for tr in trs[period:]:
        cur = (cur * (period_dec - 1) + tr) / period_dec
    return cur


def bollinger_bands(
    bars: list[Bar],
    period: int = 20,
    std: float = 2.0,
) -> tuple[Decimal, Decimal, Decimal]:
    """Bollinger bands on ``close`` prices of the last ``period`` bars.

    ``bars`` MUST be oldest-first. Returns ``(lower, middle, upper)`` where
    ``middle`` is the simple moving average of the last ``period`` closes
    and the bands are ``middle ± std * stdev``.

    Raises
    ------
    ValueError
        If fewer than ``period`` bars are supplied.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if len(bars) < period:
        raise ValueError(
            f"need at least {period} bars for BB({period}), got {len(bars)}"
        )

    window = [b.close for b in bars[-period:]]
    period_dec = Decimal(period)
    mean = sum(window, Decimal("0")) / period_dec
    variance = sum((c - mean) * (c - mean) for c in window) / period_dec
    # Decimal has no sqrt for arbitrary precision; use Decimal's sqrt()
    # via the default context — acceptable for band-width precision.
    stdev = variance.sqrt()
    std_dec = Decimal(str(std))
    return (mean - std_dec * stdev, mean, mean + std_dec * stdev)


def size_by_atr(
    *,
    equity: Decimal,
    atr_px: Decimal,
    risk_per_trade_pct: Decimal,
    atr_sl_mult: Decimal,
) -> Decimal:
    """Position sizing targeting ``risk_per_trade_pct`` of equity.

    ``risk_per_trade_pct`` is a FRACTION (e.g. ``Decimal('0.01')`` for 1%).
    The stop distance is ``atr_px * atr_sl_mult`` — qty is chosen so that a
    full-stop move loses exactly ``equity * risk_per_trade_pct``.

    Example: equity=$1000, atr=$2, risk=1% (0.01), mult=2 →
    stop_distance=$4, risk_usd=$10, qty = 10/4 = 2.5.
    """
    if atr_px <= 0 or atr_sl_mult <= 0:
        raise ValueError("atr_px and atr_sl_mult must be positive")
    stop_distance = atr_px * atr_sl_mult
    risk_usd = equity * risk_per_trade_pct
    return risk_usd / stop_distance


def apply_notional_cap(
    qty: Decimal,
    entry_px: Decimal,
    notional_cap_usd: Decimal,
) -> Decimal:
    """Clamp ``qty`` so that ``qty * entry_px <= notional_cap_usd``.

    Layer 1 of the two-layer notional cap (Layer 2 is the executor
    ``NotionalCapExceeded`` assertion in Phase 7 Task 6). Belt-and-
    suspenders defense for SIZING-WK1 at $10 micro-size.
    """
    if entry_px <= 0:
        raise ValueError(f"entry_px must be positive, got {entry_px}")
    cap_qty = notional_cap_usd / entry_px
    return qty if qty <= cap_qty else cap_qty


def in_cooldown(
    last_exit_at: datetime | None,
    cooldown_td: timedelta,
    now: datetime,
) -> bool:
    """True if ``now`` is within the cooldown window after ``last_exit_at``.

    ``None`` for ``last_exit_at`` means "never exited" — NOT in cooldown.
    """
    if last_exit_at is None:
        return False
    return last_exit_at + cooldown_td > now


def sma(bars: list[Bar], period: int) -> Decimal:
    """Simple moving average of ``close`` over the last ``period`` closed bars.

    ``bars`` MUST be ordered oldest-first. Returns the SMA computed over
    ``bars[-period:]``. Pure helper — no IO, no side effects. Used by the
    V24 XSM triple-bear regime filter (Phase 9, STRAT-HL-07) and the XSM
    ranker (breadth + trend filters).

    Raises
    ------
    ValueError
        If fewer than ``period`` bars are supplied.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if len(bars) < period:
        raise ValueError(f"sma requires at least {period} bars, got {len(bars)}")
    return sum((b.close for b in bars[-period:]), start=Decimal("0")) / Decimal(period)


def cci(bars: list[Bar], period: int = 20) -> Decimal:
    """Commodity Channel Index over the last ``period`` closed bars (Phase 8, Task 2).

    ``CCI = (typical_price - sma(typical_price, period)) / (0.015 * mean_deviation)``
    where ``typical_price = (high + low + close) / 3``.

    Canonical interpretation:

    * ``CCI > +100`` — price is sufficiently above its recent mean to be
      considered "overbought" (reversal-strategy short entry).
    * ``CCI < -100`` — oversold (reversal-strategy long entry).

    ``bars`` MUST be ordered oldest-first. Returns the CCI for the LAST bar
    in the supplied window. Requires ``len(bars) >= period``.

    Returns ``Decimal('0')`` when mean deviation is zero (flat bars) — the
    canonical definition is undefined in that case; 0 is the safest signal-
    free value for reversal strategies that gate on |CCI| > threshold.

    Raises
    ------
    ValueError
        If fewer than ``period`` bars are supplied.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if len(bars) < period:
        raise ValueError(
            f"cci requires at least {period} bars, got {len(bars)}"
        )

    window = bars[-period:]
    period_dec = Decimal(period)
    tps = [(b.high + b.low + b.close) / Decimal("3") for b in window]
    sma = sum(tps, Decimal("0")) / period_dec
    mean_dev = sum((abs(tp - sma) for tp in tps), Decimal("0")) / period_dec
    if mean_dev == 0:
        return Decimal("0")
    return (tps[-1] - sma) / (Decimal("0.015") * mean_dev)


__all__ = [
    "EntrySignal",
    "Strategy",
    "apply_notional_cap",
    "atr",
    "bollinger_bands",
    "cci",
    "in_cooldown",
    "size_by_atr",
    "sma",
]
