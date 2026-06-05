"""Rail 8 — single-coin concentration > 40% of portfolio (RAIL-09, Phase 10 Task 5).

Aggregates exposure across ALL sleeves per symbol (e.g. BTC via XSM +
BTC via a hypothetical USER sleeve); if any single symbol's notional
exceeds 40% of portfolio equity, fires with ``action=REFUSE_ENTRY``.

Pure function. Caller supplies:

* ``open_positions`` — list of Position-like rows across the whole
  portfolio.
* ``portfolio_equity_usd`` — aggregate equity.
* ``current_mark_px_by_symbol`` — fresh marks for notional computation.
  If a symbol is missing the mark, falls back to ``position.entry_px``.

Strict-``>`` boundary. Exactly at 40.00% does NOT fire.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from backend.app.engine.rails.framework import (
    RailAction,
    RailId,
    RailResult,
    RailSeverity,
)


def rail_08_concentration(
    *,
    open_positions: list[Any] | tuple[Any, ...],
    portfolio_equity_usd: Decimal,
    current_mark_px_by_symbol: dict[str, Decimal] | None = None,
    threshold_pct: Decimal = Decimal("40.0"),
) -> RailResult:
    """Refuse new entries when any single symbol > 40% of portfolio equity."""
    marks = current_mark_px_by_symbol or {}
    by_symbol: dict[str, Decimal] = {}
    for pos in open_positions:
        sym = getattr(pos, "symbol", None)
        qty = Decimal(str(getattr(pos, "qty", 0)))
        entry = Decimal(str(getattr(pos, "entry_px", 0)))
        if sym is None:
            continue
        px = marks.get(sym, entry)
        # Absolute notional — shorts contribute positive exposure too.
        exposure = (px * qty).copy_abs()
        by_symbol[sym] = by_symbol.get(sym, Decimal("0")) + exposure

    if portfolio_equity_usd <= 0:
        payload: dict[str, Any] = {
            "by_symbol_usd": {k: str(v) for k, v in by_symbol.items()},
            "portfolio_equity_usd": str(portfolio_equity_usd),
            "threshold_pct": str(threshold_pct),
        }
        return RailResult(
            rail_id=RailId.CONCENTRATION_40,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message="portfolio_equity <= 0; concentration skipped",
        )

    breaching = []
    for sym, exposure in by_symbol.items():
        pct = (exposure / portfolio_equity_usd) * Decimal("100")
        if pct > threshold_pct:
            breaching.append({"coin": sym, "pct": str(pct), "exposure_usd": str(exposure)})

    payload = {
        "by_symbol_usd": {k: str(v) for k, v in by_symbol.items()},
        "portfolio_equity_usd": str(portfolio_equity_usd),
        "threshold_pct": str(threshold_pct),
        "breaching_coins": breaching,
    }
    if not breaching:
        return RailResult(
            rail_id=RailId.CONCENTRATION_40,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message="no symbol breaches concentration threshold",
        )
    return RailResult(
        rail_id=RailId.CONCENTRATION_40,
        fired=True,
        severity=RailSeverity.WARN,
        action=RailAction.REFUSE_ENTRY,
        payload=payload,
        message=(
            f"concentration breach on {[b['coin'] for b in breaching]} "
            f"> {threshold_pct}% → refuse_entry"
        ),
    )


__all__ = ["rail_08_concentration"]
