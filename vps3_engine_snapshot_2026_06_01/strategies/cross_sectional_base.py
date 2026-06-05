"""Cross-sectional strategy ABC (Phase 9, Task 3 · STRAT-HL-04).

The Phase 7 ``Strategy`` ABC produces one signal per (sleeve, bar) for
single-symbol strategies. Cross-sectional strategies are fundamentally
different: they rank ALL coins in the universe and return a LIST of
signals (top-N slots). A separate ABC is cleaner than overloading
``Strategy`` — the controller layer dispatches differently too
(``HyperliquidXsmController`` vs ``HyperliquidSleeveController``).

Invariants (same as Phase 7 Strategy):

* Pure function: ``evaluate(daily_bars_per_coin, config)`` has no IO,
  no global state, no time reads except via an injectable clock.
* No imports from ``backend.app.{venues,db,executors,engine,controllers}``
  in this module or any concrete subclass.
* All numeric fields flow as ``Decimal`` — no ``float`` leaks.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from backend.app.strategies.base import EntrySignal

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from pydantic import BaseModel

    from backend.app.data.models import Bar


class CrossSectionalStrategy(ABC):
    """Abstract base for strategies that rank all coins in a universe.

    Subclasses implement ``evaluate(daily_bars_per_coin, config)`` —
    returns up to ``config.max_slots`` ``EntrySignal`` objects, or an
    empty list if no slots should be opened this wake.
    """

    @abstractmethod
    def evaluate(
        self,
        daily_bars_per_coin: dict[str, list[Bar]],
        config: BaseModel,
    ) -> list[EntrySignal]:
        """Produce zero-or-more entry signals for this rebalance wake.

        Parameters
        ----------
        daily_bars_per_coin:
            Mapping coin → list of daily bars (oldest-first). Every coin
            in ``config.universe`` must be present.
        config:
            Sleeve config — must expose at least ``universe``,
            ``max_slots``, ``notional_per_slot_usd`` on the concrete type.

        Returns
        -------
        list[EntrySignal]
            Empty when a regime filter fires or no ranks qualify; up to
            ``config.max_slots`` signals otherwise, ordered by score
            descending.
        """


__all__ = ["CrossSectionalStrategy", "EntrySignal"]
