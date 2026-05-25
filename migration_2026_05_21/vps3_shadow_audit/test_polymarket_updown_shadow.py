"""Phase 23 Plan 04 — shadow audit writer tests.

Covers the three new audit-row writers cloned from `_audit_hedge_skip`:

- `_audit_shadow_simulated`         — entry phase on rail-block (D-22 / D-24)
- `_audit_shadow_paper_resolved`    — paired exit on next-bar boundary (D-26)
- `_audit_shadow_counterfactual`    — sleeves not armed live (D-23)

Plus the resolution sweep (`_resolve_pending_shadow_entries`) at top of `on_tick`.

D-22 hard rule: NO `trading.shadow_trades` schema. All rows go into
`trading.events` with new `kind` discriminators.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.controllers.polymarket_updown import (
    PolymarketUpdownController,
    Slot,
)


# ----------------------------------------------------------------------
# Capturing fake pool — records (sql, args) for every `execute` call.
# ----------------------------------------------------------------------


class _CapturingConn:
    def __init__(self, inserts: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._inserts = inserts

    async def execute(self, sql: str, *args: Any) -> str:
        self._inserts.append((sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return []

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        return None


class _CapturingAcquire:
    def __init__(self, inserts: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._inserts = inserts

    async def __aenter__(self) -> _CapturingConn:
        return _CapturingConn(self._inserts)

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _CapturingPool:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> _CapturingAcquire:
        return _CapturingAcquire(self.inserts)


class _RaisingPool:
    """Pool whose acquire() raises — exercises the swallow-discipline."""

    def acquire(self) -> Any:
        raise RuntimeError("pool exploded")


def _make_executor() -> MagicMock:
    executor = MagicMock()
    executor.place_entry_order = AsyncMock(
        return_value=MagicMock(order_id="paper-1"),
    )
    executor.place_exit_order = AsyncMock(
        return_value=MagicMock(order_id="paper-exit-1"),
    )
    executor.get_orderbook_snapshot = AsyncMock(
        return_value={
            "asks": [{"price": "0.55", "size": "1000"}],
            "bids": [{"price": "0.53", "size": "1000"}],
            "ts": 0,
        },
    )
    return executor


def _make_slot(
    *,
    symbol: str = "BTC",
    tf: str = "5m",
    signal: str = "UP",
    slot_id: str = "abc",
    condition_id: str = "0xC0DE",
) -> Slot:
    return Slot(
        sleeve_id=f"poly_updown_{symbol.lower()}_{tf}_volume",
        symbol=symbol,
        tf=tf,
        condition_id=condition_id,
        signal=signal,  # type: ignore[arg-type]
        entry_price=Decimal("0.50"),
        entry_qty=Decimal("49"),
        btc_close_at_ws=Decimal("0"),
        binance_symbol_id="OKX_SPOT_BTC_USDT",
        slot_id=slot_id,
    )


def _make_controller(
    *,
    pool: Any,
    strategy_mode: str = "volume",
) -> PolymarketUpdownController:
    return PolymarketUpdownController(
        pool=pool,
        executor=_make_executor(),
        mode="paper",
        strategy_mode=strategy_mode,  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------------
# Test 1: _audit_shadow_simulated writes one row with the correct shape
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_shadow_simulated_writes_entry_row() -> None:
    pool = _CapturingPool()
    controller = _make_controller(pool=pool)
    slot = _make_slot()

    await controller._audit_shadow_simulated(
        slot,
        reason="confidence_low",
        entry_price=0.51,
        qty=49.0,
        signal_strength=0.74,
    )

    assert len(pool.inserts) == 1
    sql, args = pool.inserts[0]
    assert "INSERT INTO trading.events" in sql
    assert "'shadow_simulated'" in sql
    sleeve_agg_id, payload_json = args
    assert sleeve_agg_id == "poly_updown_btc_5m_volume"
    import json as _json
    payload = _json.loads(payload_json)
    assert payload["slot_id"] == "abc"
    assert payload["condition_id"] == "0xC0DE"
    assert payload["signal"] == "UP"
    assert payload["reason"] == "confidence_low"
    assert payload["mode"] == "paper"
    assert payload["entry_price"] == 0.51
    assert payload["qty"] == 49.0
    assert payload["signal_strength"] == 0.74
    assert "entry_ts" in payload  # timestamp present
    # bar_close_ts is None when slot doesn't carry one.
    assert "bar_close_ts" in payload


# ----------------------------------------------------------------------
# Test 2: _audit_shadow_paper_resolved writes paired exit row
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_shadow_paper_resolved_writes_exit_row() -> None:
    pool = _CapturingPool()
    controller = _make_controller(pool=pool)
    slot = _make_slot()

    await controller._audit_shadow_paper_resolved(
        slot,
        exit_price=0.535,
        realized_pnl_usd=1.225,
        bar_close_ts="2026-05-05T15:30:00Z",
    )

    assert len(pool.inserts) == 1
    sql, args = pool.inserts[0]
    assert "INSERT INTO trading.events" in sql
    # The EXIT row uses kind='shadow_simulated_exit' so the canonical
    # /shadow/sleeves/{id} JOIN can pair entries with exits.
    assert "'shadow_simulated_exit'" in sql
    sleeve_agg_id, payload_json = args
    assert sleeve_agg_id == "poly_updown_btc_5m_volume"
    import json as _json
    payload = _json.loads(payload_json)
    assert payload["exit_price"] == 0.535
    assert payload["realized_pnl_usd"] == 1.225
    assert payload["bar_close_ts"] == "2026-05-05T15:30:00Z"
    assert payload["slot_id"] == "abc"
    assert "exit_ts" in payload


# ----------------------------------------------------------------------
# Test 3: _audit_shadow_counterfactual writes counterfactual row
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_shadow_counterfactual_writes_row() -> None:
    pool = _CapturingPool()
    controller = _make_controller(pool=pool, strategy_mode="sniper")
    slot = _make_slot()

    await controller._audit_shadow_counterfactual(
        slot,
        signal_strength=0.74,
    )

    assert len(pool.inserts) == 1
    sql, args = pool.inserts[0]
    assert "INSERT INTO trading.events" in sql
    assert "'shadow_counterfactual'" in sql
    sleeve_agg_id, payload_json = args
    # strategy_mode='sniper' → suffix '_sniper'
    assert sleeve_agg_id == "poly_updown_btc_5m_sniper"
    import json as _json
    payload = _json.loads(payload_json)
    assert payload["signal_strength"] == 0.74
    assert payload["armed"] is False
    assert payload["mode"] == "paper"
    assert payload["signal"] == "UP"


# ----------------------------------------------------------------------
# Test 4: pool errors are swallowed — best-effort discipline
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_shadow_simulated_swallows_pool_error() -> None:
    controller = _make_controller(pool=_RaisingPool())
    slot = _make_slot()
    # Must NOT raise. Returns None.
    result = await controller._audit_shadow_simulated(
        slot, reason="any", entry_price=0.5, qty=49.0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_audit_shadow_paper_resolved_swallows_pool_error() -> None:
    controller = _make_controller(pool=_RaisingPool())
    slot = _make_slot()
    result = await controller._audit_shadow_paper_resolved(
        slot, exit_price=0.5, realized_pnl_usd=0.0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_audit_shadow_counterfactual_swallows_pool_error() -> None:
    controller = _make_controller(pool=_RaisingPool())
    slot = _make_slot()
    result = await controller._audit_shadow_counterfactual(
        slot, signal_strength=0.7,
    )
    assert result is None


@pytest.mark.asyncio
async def test_audit_shadow_simulated_pool_none_no_op() -> None:
    # pool=None branch: returns immediately, writes nothing.
    controller = PolymarketUpdownController(
        pool=None, executor=_make_executor(), mode="paper",  # type: ignore[arg-type]
    )
    slot = _make_slot()
    result = await controller._audit_shadow_simulated(
        slot, reason="any", entry_price=0.5, qty=49.0,
    )
    assert result is None


# ----------------------------------------------------------------------
# Test 5: sleeve_id canonical form across V3-portfolio split
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sleeve_id_canonical_form_volume() -> None:
    pool = _CapturingPool()
    controller = _make_controller(pool=pool, strategy_mode="volume")
    slot = _make_slot(symbol="BTC", tf="5m")
    await controller._audit_shadow_simulated(
        slot, reason="x", entry_price=0.5, qty=49.0,
    )
    sleeve_agg_id = pool.inserts[0][1][0]
    assert sleeve_agg_id == "poly_updown_btc_5m_volume"
    assert sleeve_agg_id.endswith("_volume")


@pytest.mark.asyncio
async def test_sleeve_id_canonical_form_sniper() -> None:
    pool = _CapturingPool()
    controller = _make_controller(pool=pool, strategy_mode="sniper")
    slot = _make_slot(symbol="ETH", tf="15m")
    await controller._audit_shadow_simulated(
        slot, reason="x", entry_price=0.5, qty=49.0,
    )
    sleeve_agg_id = pool.inserts[0][1][0]
    assert sleeve_agg_id == "poly_updown_eth_15m_sniper"
    assert sleeve_agg_id.endswith("_sniper")


@pytest.mark.asyncio
async def test_sleeve_id_canonical_form_v3() -> None:
    pool = _CapturingPool()
    controller = _make_controller(pool=pool, strategy_mode="v3")
    slot = _make_slot(symbol="SOL", tf="5m")
    await controller._audit_shadow_counterfactual(
        slot, signal_strength=0.85,
    )
    sleeve_agg_id = pool.inserts[0][1][0]
    assert sleeve_agg_id == "poly_updown_sol_5m_v3"
    assert sleeve_agg_id.endswith("_v3")


# ----------------------------------------------------------------------
# Test 6: bar_close_ts override + entry_ts ISO format
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_shadow_simulated_bar_close_ts_attribute() -> None:
    """Slot.bar_close_ts attribute, when set, flows into payload."""
    pool = _CapturingPool()
    controller = _make_controller(pool=pool)
    slot = _make_slot()
    # Set bar_close_ts dynamically — the writer reads via getattr.
    slot.bar_close_ts = "2026-05-05T15:30:00Z"  # type: ignore[attr-defined]
    await controller._audit_shadow_simulated(
        slot, reason="x", entry_price=0.5, qty=49.0,
    )
    import json as _json
    payload = _json.loads(pool.inserts[0][1][1])
    assert payload["bar_close_ts"] == "2026-05-05T15:30:00Z"
    # entry_ts must be ISO-formatted UTC.
    entry_ts = payload["entry_ts"]
    parsed = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


# ----------------------------------------------------------------------
# Test 7: resolution sweep (_resolve_pending_shadow_entries) is reachable
# ----------------------------------------------------------------------


class _SweepFakeConn:
    """Connection that returns one open shadow entry, no existing exit."""

    def __init__(self, inserts: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._inserts = inserts

    async def execute(self, sql: str, *args: Any) -> str:
        self._inserts.append((sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        # Return one pending shadow_simulated row.
        return [
            {
                "slot_id": "slot-1",
                "entry_price": Decimal("0.50"),
                "qty": Decimal("49"),
                "bar_close_ts": "2026-05-05T15:30:00Z",
                "condition_id": "0xC0DE",
            },
        ]

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        return None


class _SweepAcquire:
    def __init__(self, inserts: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._inserts = inserts

    async def __aenter__(self) -> _SweepFakeConn:
        return _SweepFakeConn(self._inserts)

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _SweepPool:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> _SweepAcquire:
        return _SweepAcquire(self.inserts)


@pytest.mark.asyncio
async def test_resolve_pending_shadow_entries_writes_paired_exit() -> None:
    pool = _SweepPool()
    controller = _make_controller(pool=pool)
    # The executor returns a mid 0.55 (best_bid 0.53, best_ask 0.55 → mid 0.54)
    controller.executor.get_orderbook_snapshot = AsyncMock(
        return_value={
            "bids": [{"price": "0.53", "size": "1000"}],
            "asks": [{"price": "0.55", "size": "1000"}],
            "ts": 0,
        },
    )
    await controller._resolve_pending_shadow_entries(
        "poly_updown_btc_5m_volume",
    )
    # Should write at least one exit row.
    assert any(
        "'shadow_simulated_exit'" in sql for sql, _args in pool.inserts
    ), pool.inserts


@pytest.mark.asyncio
async def test_resolve_pending_shadow_entries_swallows_errors() -> None:
    """Sweep over a raising pool returns None silently."""
    controller = _make_controller(pool=_RaisingPool())
    result = await controller._resolve_pending_shadow_entries(
        "poly_updown_btc_5m_volume",
    )
    assert result is None


# ----------------------------------------------------------------------
# Test 8: _resolve_pending_shadow_entries is called from on_tick
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_tick_invokes_resolve_pending_shadow_entries() -> None:
    pool = _CapturingPool()
    controller = _make_controller(pool=pool)
    # Spy on the resolution sweep — patch onto the bound method namespace.
    spy = AsyncMock()
    controller._resolve_pending_shadow_entries = spy  # type: ignore[method-assign]
    await controller.on_tick()
    # Called once per active sleeve_id (volume default → "poly_updown_*_volume" set).
    # Just assert it was invoked at least once.
    assert spy.await_count >= 1
