"""V24 XSM cross-sectional multi-filter strategy (Phase 9, Task 3 · STRAT-HL-04).

Clean-room port of Fullproject's ``low_dd_xsm(mode='multi_filter')``.
Ranks the 9-coin universe by a composite of three signals and returns up
to ``config.max_slots`` long signals. Triple-bear regime filter (Phase 9
Task 2) gates entry entirely — if it fires, returns ``[]`` and the
controller flattens the sleeve.

Composite score (per 09-CONTEXT D-03):

    composite = 0.5 * (1 - dd_90d)
              + 0.3 * above_50d
              + 0.2 * (1 / (1 + relative_atr))

where:

* ``dd_90d`` — 1 - (last_close / max_close_in_90d_window); low DD → score ↑.
* ``above_50d`` — binary; 1 if close > 50d SMA, else 0.
* ``relative_atr`` — ``atr(bars, N) / last_close``; low vol → score ↑.

Hard filter: coins with ``above_50d == 0`` (in downtrend) are EXCLUDED
before ranking — a long-only XSM should never buy downtrend coins even
if their DD or vol scores are favorable.

Invariants:

* Pure function. No IO, no imports from
  ``backend.app.{venues,db,executors,engine,controllers}``.
* ``EntrySignal.limit_px`` uses the LAST CLOSED bar's close — never
  peeks at an unclosed bar (CLAUDE.md invariant #4).
* All numeric fields are ``Decimal``.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from backend.app.strategies.base import EntrySignal, atr, sma
from backend.app.strategies.cross_sectional_base import CrossSectionalStrategy
from backend.app.strategies.hyperliquid.regime_filter import triple_bear_filter

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar
    from backend.app.strategies.hyperliquid.v24_xsm_config import V24XSMConfig


def _composite_score(
    *,
    dd_90d: Decimal,
    above_50d: int,
    relative_atr: Decimal,
) -> Decimal:
    """Weighted composite — higher is better."""
    one = Decimal("1")
    return (
        Decimal("0.5") * (one - dd_90d)
        + Decimal("0.3") * Decimal(above_50d)
        + Decimal("0.2") * (one / (one + relative_atr))
    )


class V24XSMMultiFilterStrategy(CrossSectionalStrategy):
    """Cross-sectional ranker — long-only XSM on the frozen 9-coin universe."""

    def evaluate(
        self,
        daily_bars_per_coin: dict[str, list[Bar]],
        config: V24XSMConfig,  # type: ignore[override]
    ) -> list[EntrySignal]:
        """Rank coins, apply triple-bear filter, return up to ``max_slots`` signals."""

        # --- Regime filter (STRAT-HL-07) ---------------------------------
        btc_daily = daily_bars_per_coin["BTC"]
        regime = triple_bear_filter(
            btc_daily=btc_daily,
            universe_daily={
                coin: daily_bars_per_coin[coin] for coin in config.universe
            },
            btc_sma_long_days=config.btc_sma_long_days,
            btc_sma_short_days=config.btc_sma_short_days,
            breadth_sma_days=config.breadth_sma_days,
            breadth_min_above=config.breadth_min_above,
        )
        if regime.fired:
            return []

        # --- Rank ---------------------------------------------------------
        scored: list[tuple[str, Decimal, Decimal, Decimal]] = []
        for coin in config.universe:
            bars = daily_bars_per_coin[coin]
            last_close = bars[-1].close

            # DD over last dd_lookback_days
            window = bars[-config.dd_lookback_days:]
            max_close = max(b.close for b in window)
            dd_90d = Decimal("1") - (last_close / max_close) if max_close > 0 else Decimal("0")

            # Above 50d SMA?
            coin_50 = sma(bars, config.breadth_sma_days)
            above_50d = 1 if last_close > coin_50 else 0
            if not above_50d:
                # Long-only XSM — skip downtrend coins entirely.
                continue

            # Relative ATR (volatility — lower is better)
            atr_px = atr(bars, config.relative_atr_period)
            rel_atr = atr_px / last_close if last_close > 0 else Decimal("0")

            score = _composite_score(
                dd_90d=dd_90d, above_50d=above_50d, relative_atr=rel_atr
            )
            scored.append((coin, score, last_close, atr_px))

        # Sort by score descending, take top max_slots.
        scored.sort(key=lambda row: row[1], reverse=True)
        selected = scored[: config.max_slots]

        # --- Build signals -----------------------------------------------
        signals: list[EntrySignal] = []
        for coin, _score, last_close, atr_px in selected:
            qty = config.notional_per_slot_usd / last_close
            sl_px = last_close - config.sl_atr_mult * atr_px
            tp_px = last_close + config.tp_atr_mult * atr_px
            signals.append(
                EntrySignal(
                    symbol=coin,
                    side="long",
                    qty=qty,
                    limit_px=last_close,
                    sl_px=sl_px,
                    tp_px=tp_px,
                    atr_px=atr_px,
                    max_hold_td=timedelta(weeks=config.max_hold_weeks),
                    cooldown_td=timedelta(weeks=config.cooldown_weeks),
                )
            )
        return signals


__all__ = ["V24XSMMultiFilterStrategy"]
