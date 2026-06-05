"""DOGE HTF Donchian breakout strategy (Phase 8, Task 3 · STRAT-HL-02).

Clean-room port per 08-CONTEXT D-03 — Fullproject source is external to this
worktree, so this implementation follows the documented recipe:

* 20-bar Donchian channel on ``bars[:-1]`` (look-ahead guard — the candidate
  bar cannot participate in its own Donchian).
* HTF trend filter: ``bars[-1].close`` compared to ``bars[-1-htf_period].close``.
* Long entry: ``close > donchian_high AND htf_uptrend``.
* Short entry: ``close < donchian_low AND htf_downtrend``.
* ATR-based sizing + SL / TP / trail.

Invariants:

* Pure function of (``bars``, ``self.config``) — zero IO, zero imports from
  ``backend.app.(venues|db|executors|engine|controllers)``.
* ``bars`` assumed oldest-first (chronological ascending). Phase 4's
  ``get_bars`` returns newest-first; the BarEngine dispatch reverses before
  calling ``on_bar_close`` (verified by Phase 7 Task 5).
* Sizing: ``size_by_atr`` + ``apply_notional_cap`` enforce the $10 notional
  cap at the strategy layer; the executor repeats the assertion.

CLAUDE.md invariants honored:

* #4 — strategy receives only closed bars.
* #3 — 5s post-boundary buffer is enforced upstream.
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
    size_by_atr,
)

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar
    from backend.app.strategies.hyperliquid.htf_donchian_config import HTFDonchianConfig


def _tf_to_td(tf: str, bars: int) -> timedelta:
    """Translate ``(tf, bars)`` into a ``timedelta``.

    Mirrors ``bbbreak_ls._tf_to_td`` — duplicated here to preserve the
    zero-cross-strategy-import discipline (strategies are peers, not a tree).
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
    raise ValueError(f"unsupported timeframe for HTFDonchian: {tf!r}")


class HTFDonchianStrategy(Strategy):
    """20-bar Donchian break with 5-bar higher-timeframe trend filter.

    Config is bound at ``__init__`` and held on ``self.config`` — matches the
    ``Strategy`` Protocol used by ``HyperliquidSleeveController``.
    """

    def __init__(self, config: HTFDonchianConfig) -> None:
        self.config = config

    def evaluate(self, bars: list[Bar]) -> EntrySignal | None:
        """Inspect ``bars`` (oldest-first); return a signal or ``None``.

        Algorithm:

        1. Require at least ``max(donchian_period, atr_period) + htf_period + 1``
           closed bars — Donchian needs ``donchian_period`` prior bars, HTF
           filter needs ``htf_period`` lookback, ATR needs ``atr_period + 1``.
        2. Compute ATR on the full window.
        3. Donchian channel on ``bars[-donchian_period-1:-1]`` (last ``donchian_period``
           bars BEFORE the candidate bar — no self-inclusion).
        4. HTF filter: ``bars[-1].close`` vs ``bars[-1-htf_period].close``.
        5. Long: ``close > donchian_high AND close > htf_ref_close``.
           Short: ``close < donchian_low AND close < htf_ref_close``.
        6. Size by ATR, clamp by notional cap, build SL / TP.
        """
        cfg = self.config
        donchian_p = cfg.donchian_period
        htf_p = cfg.htf_period
        atr_p = cfg.atr_period

        # Lookback requirement: donchian window ends at bars[-2], spans
        # donchian_p bars → needs indices [-donchian_p-1 .. -2] valid, i.e.
        # len(bars) >= donchian_p + 1.
        # HTF filter needs bars[-1-htf_p] valid → len(bars) >= htf_p + 1.
        # ATR needs atr_p + 1 bars.
        min_required = max(donchian_p + 1, atr_p + 1, htf_p + 1)
        if len(bars) < min_required:
            return None

        # ATR on the full window (ATR needs period + 1 bars for TR).
        atr_px = atr(bars, atr_p)
        if atr_px <= 0:
            return None

        # Donchian channel on bars[-donchian_p-1:-1] — excludes bars[-1].
        prior = bars[-donchian_p - 1 : -1]
        if len(prior) < donchian_p:
            return None
        donchian_high = max(b.high for b in prior)
        donchian_low = min(b.low for b in prior)

        close_px = bars[-1].close
        htf_ref_close = bars[-1 - htf_p].close

        side: str | None = None
        if close_px > donchian_high and close_px > htf_ref_close:
            side = "long"
        elif close_px < donchian_low and close_px < htf_ref_close:
            side = "short"
        else:
            return None

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


__all__ = ["HTFDonchianStrategy"]
