"""Wilder-style RSI(14) on 1MIN binance closes.

Provides two flavors:

* :class:`RSI14` — streaming state machine. Update on each new closed
  1MIN bar; read ``.value`` at signal time. Used when the controller
  wants to maintain RSI across many ticks without recomputing.

* :func:`compute_rsi_14` — pure function. Takes a list of ≥15 closes and
  returns the RSI value at the LAST close. Used when the controller
  already has the closes in hand (e.g. via
  ``BinanceMarketDataFeed.get_closes_window``) and just wants the
  current reading without keeping streaming state.

Both implementations are **log-return based** to match the backtest
reference in
``strategy_lab/meta_classifier/momo_filter_overlay.py:attach_kline_features``:

    log_rets[1:] = np.log(close[1:] / close[:-1])
    roll_up[14:] = (cumsum_up[14:] - cumsum_up[:-14]) / 14
    roll_dn[14:] = (cumsum_dn[14:] - cumsum_dn[:-14]) / 14
    rsi = 100 - 100 / (1 + roll_up / roll_dn)

Validation tolerance vs reference: ±0.5 RSI units on the first 50 bars
(spec §2 "Validation against backtest").

Edge cases (TV_AGENT_F7_RSI_FILTER_SPEC §2):

* First 14 bars of stream → :attr:`RSI14.value` returns ``nan`` (caller
  treats nan as "skip the fire" via :func:`f7_gate.f7_passes`).
* Bad input (``close = 0``, ``nan``, negative): skipped; prev_close
  retained; gains/losses deque untouched.
* Constant prices: ``avg_dn == 0`` → returns 100.0 (RSI ceiling).
* Constant declines: ``avg_up == 0`` → returns 0.0 (RSI floor).

CLAUDE.md inv #4: this module is PURE — no IO, no time.time(), no
mutation of inputs. Streaming :class:`RSI14` mutates only its own
private state; pure :func:`compute_rsi_14` is referentially transparent.
"""
from __future__ import annotations

import math
from collections import deque

__all__ = ["RSI14", "compute_rsi_14"]

#: RSI period — fixed at Wilder's canonical 14.
_PERIOD: int = 14


def _log_return(prev_close: float, close: float) -> float:
    """``log(close / prev_close)`` — log-return between two closes.

    Returns ``nan`` if either input is non-positive or non-finite. Caller
    treats nan as "skip this bar's update" (see ``RSI14.update``).
    """
    if (
        not math.isfinite(prev_close)
        or not math.isfinite(close)
        or prev_close <= 0
        or close <= 0
    ):
        return float("nan")
    return math.log(close / prev_close)


class RSI14:
    """Streaming Wilder RSI(14) on log-returns of 1MIN closes.

    Usage::

        rsi = RSI14()
        for c in closes_chronological:   # feed in time order
            rsi.update(c)
        current = rsi.value              # float; NaN until 14 bars in

    State:
        * ``prev_close`` — last accepted close (used to compute next
          log-return). ``None`` until first valid update.
        * ``gains`` / ``losses`` — last-14 positive / negative log-return
          deques. Fixed-size ``maxlen=14`` → automatic eviction of the
          oldest sample on the 15th update.

    Thread-safety: NONE. Designed to be owned by a single async task
    per (asset, timeframe). Concurrent ``update()`` calls from multiple
    tasks race on ``prev_close`` and corrupt state.
    """

    PERIOD: int = _PERIOD

    __slots__ = ("prev_close", "gains", "losses")

    def __init__(self) -> None:
        self.prev_close: float | None = None
        self.gains: deque[float] = deque(maxlen=_PERIOD)
        self.losses: deque[float] = deque(maxlen=_PERIOD)

    def update(self, close: float) -> None:
        """Ingest one new closed 1MIN close.

        Bad input (non-finite, ≤0) is dropped — ``prev_close`` retained,
        deques untouched. This protects against feed glitches (rare
        Binance 0-close on stream re-handshake) without polluting RSI.

        The FIRST valid close just sets ``prev_close``; no log-return
        is computed (need two closes to make a return). From the second
        valid close onward, each call appends one sample to the deques.
        """
        if not math.isfinite(close) or close <= 0:
            # Bad input — drop. Keep prev_close so next valid close
            # can still produce a log-return.
            return
        if self.prev_close is None:
            self.prev_close = close
            return
        ret = _log_return(self.prev_close, close)
        if math.isfinite(ret):
            self.gains.append(ret if ret > 0 else 0.0)
            self.losses.append(-ret if ret < 0 else 0.0)
        self.prev_close = close

    @property
    def value(self) -> float:
        """Current RSI value, or NaN if fewer than 14 returns accumulated.

        Wilder formula (simple-moving-average flavor — matches the
        backtest reference, NOT the exponential-smoothing variant)::

            avg_up = mean(gains[-14:])
            avg_dn = mean(losses[-14:])
            if avg_dn == 0: return 100.0
            if avg_up == 0: return 0.0
            rs = avg_up / avg_dn
            return 100.0 - 100.0 / (1.0 + rs)
        """
        if len(self.gains) < _PERIOD:
            return float("nan")
        avg_up = sum(self.gains) / _PERIOD
        avg_dn = sum(self.losses) / _PERIOD
        if avg_dn == 0:
            return 100.0
        if avg_up == 0:
            return 0.0
        rs = avg_up / avg_dn
        return 100.0 - 100.0 / (1.0 + rs)

    def reset(self) -> None:
        """Clear all state. Used by controllers on feed-gap recovery."""
        self.prev_close = None
        self.gains.clear()
        self.losses.clear()


def compute_rsi_14(closes: list[float]) -> float:
    """Pure RSI(14) over a list of closes ending at the most-recent bar.

    Equivalent to feeding ``closes`` chronologically to a fresh
    ``RSI14`` and reading ``.value``. Use this when the controller
    already has the closes in hand (e.g. from
    ``BinanceMarketDataFeed.get_closes_window``) — saves the need for
    a separate streaming state.

    Args:
        closes: List of float closes ordered chronologically (oldest
            first, most-recent last). At least 15 closes are needed to
            produce a non-NaN RSI (1 to seed prev_close + 14 to fill
            the gains/losses windows).

    Returns:
        The RSI value at the last close. NaN if fewer than 15 valid
        closes; 100.0 if no losses; 0.0 if no gains.
    """
    if not closes or len(closes) < _PERIOD + 1:
        return float("nan")
    rsi = RSI14()
    for c in closes:
        rsi.update(c)
    return rsi.value
