"""KalshiEventLogger — writes Kalshi shadow fires/resolutions to trading.events.

Phase 38. The KalshiUpdownController emits per-fire + per-resolution audit
payloads via an injectable ``shadow_logger.log(payload)`` sink. This adapter is
that sink: it turns each payload into a canonical ``trading.events`` row so the
Kalshi sleeve surfaces in the dashboard exactly like the Polymarket UpDown
sleeves (same read endpoints, same normalizer).

Kalshi is the SAME strategy *class* as Polymarket UpDown (``updown``) on a
different venue, so it reuses the canonical event kinds:
- ``poly_updown_signal`` per fire eval (placed or skipped) — drives fire counts
  + ``gates_evaluated`` hit-rates.
- ``poly_updown_resolution`` (``event_type='sleeve_fire_resolved'``) on settle —
  drives WR + PnL. Shape matches ``audit_schema.normalize_resolution_payload``.

PnL: a Kalshi NO/YES buy at ``fill_vwap`` (cents) for ``fill_shares`` contracts
pays $1/contract on a win → ``(1 - vwap) * shares`` profit; ``-vwap * shares``
loss; minus the flat shadow fee. Entry fill is correlated to its resolution by
``(sleeve_id, ticker)`` (resolve() carries no entry order_result).

The controller calls ``.log()`` synchronously from inside the event loop, so the
DB write is fire-and-forget via ``loop.create_task`` (never blocks the hot path,
never raises into the controller).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from backend.app.strategies.sleeve_registry import parse_sym_tf

log = structlog.get_logger("backend.app.engine.kalshi_event_logger")


def _opposite(direction: str) -> str:
    d = (direction or "").upper()
    return "DOWN" if d == "UP" else "UP"


def _asset(sleeve_id: str) -> str | None:
    st = parse_sym_tf(sleeve_id)
    return st[0] if st else None


def _symbol_from_ticker(ticker: str | None) -> str | None:
    """Per-symbol from a Kalshi ticker (e.g. ``KXBTC15M-...`` → ``BTC``).

    For the ALL fan-out sleeve (sleeve_id parses to ``ALL``) the actual symbol
    lives in the ticker — tag the audit row with it so the per-symbol breakdown
    is visible even though all rows share the one ``..._all_...`` sleeve_id.
    """
    if not ticker:
        return None
    t = ticker.upper()
    if t.startswith("KXBTC"):
        return "BTC"
    if t.startswith("KXETH"):
        return "ETH"
    if t.startswith("KXSOL"):
        return "SOL"
    return None


class KalshiEventLogger:
    """``shadow_logger`` sink that persists Kalshi audit rows to trading.events."""

    def __init__(
        self,
        *,
        pool: Any,
        notional_usd: float | Any = 5.0,
        fee_usd_per_fill: float | Any = 0.0,
        mode: str = "paper",
    ) -> None:
        self._pool = pool
        self._notional = float(notional_usd)
        self._fee = float(fee_usd_per_fill)
        self._mode = mode
        # (sleeve_id, ticker) -> (fill_vwap, fill_shares); set on placed fire,
        # popped at resolution to compute PnL.
        self._entries: dict[tuple[str, str], tuple[float, float]] = {}

    # ------------------------------------------------------------------
    # shadow_logger interface
    # ------------------------------------------------------------------

    def log(self, payload: dict[str, Any]) -> None:
        """Build + schedule a trading.events row. Never raises into the caller."""
        try:
            sleeve_id = payload.get("sleeve_id")
            if not sleeve_id:
                return
            resolved = bool(payload.get("resolved"))
            won = payload.get("won")
            if resolved and won is not None:
                kind, data = self._build_resolution(payload)
            else:
                kind, data = self._build_signal(payload)
            self._schedule_insert(str(sleeve_id), kind, data)
        except Exception:  # noqa: BLE001 — audit must never break the controller
            log.warning("kalshi_event_logger.build_failed", exc_info=True)

    # ------------------------------------------------------------------
    # Row builders
    # ------------------------------------------------------------------

    def _build_signal(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        sleeve_id = str(payload["sleeve_id"])
        ticker = payload.get("ticker")
        fv = payload.get("fill_vwap")
        fs = payload.get("fill_shares")
        order_status = payload.get("order_status")
        placed = order_status == "filled" and fv is not None
        if placed and ticker:
            try:
                self._entries[(sleeve_id, str(ticker))] = (float(fv), float(fs or 0))
            except (TypeError, ValueError):
                pass
        data: dict[str, Any] = {
            "event_type": "sleeve_fire_eval",
            "venue": "kalshi",
            "mode": self._mode,
            "direction": payload.get("direction"),
            "ticker": ticker,
            "asset": payload.get("asset") or _symbol_from_ticker(ticker) or _asset(sleeve_id),
            "all_gates_passed": payload.get("all_gates_passed"),
            "gates_evaluated": payload.get("gates_evaluated") or {},
            "skip_reason": payload.get("skip_reason"),
            "spread": payload.get("spread"),
            "reason": "order_placed" if placed else "no_signal",
            "fill_status": "filled" if placed else None,
            "fill_price": str(fv) if fv is not None else None,
        }
        # S4 prewindow port — persist the computed signal aux (dev_bps / cvd /
        # fair_up / fair_edge) so the shadow audit can validate the Kalshi
        # signal compute + tune thresholds. Only present on S4 sleeves.
        s4 = payload.get("s4")
        if s4 is not None:
            data["s4"] = s4
        return "poly_updown_signal", data

    def _build_resolution(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        sleeve_id = str(payload["sleeve_id"])
        ticker = payload.get("ticker")
        won = bool(payload.get("won"))
        direction = (payload.get("direction") or "").upper()
        entry = self._entries.pop((sleeve_id, str(ticker)), None) if ticker else None
        if entry is not None:
            vwap, shares = entry
        else:
            vwap = _safe_float(payload.get("fill_vwap"))
            shares = _safe_float(payload.get("fill_shares"))
        # HEDGE_LATE early cut carries an EXPLICIT realized PnL (sell-vwap vs
        # entry) — use it directly instead of the entry-based $1/$0 settlement.
        explicit_pnl = _safe_float(payload.get("pnl_usd"))
        exit_type = payload.get("exit_type")
        pnl = explicit_pnl if explicit_pnl is not None else self._pnl(won, vwap, shares)
        # normalize_resolution_payload derives won from outcome == direction.
        outcome = direction if won else _opposite(direction)
        data: dict[str, Any] = {
            "event_type": "sleeve_fire_resolved",
            "venue": "kalshi",
            "mode": self._mode,
            "direction": direction,
            "outcome": outcome,
            "won": won,
            "pnl_usd": pnl,
            "exit_type": exit_type or "hold_to_resolve",
            "hedge_sell_vwap": _safe_float(payload.get("hedge_sell_vwap")),
            "placed_size_usd": self._notional,
            "fill_vwap": vwap,
            "fill_shares": shares,
            "asset": payload.get("asset") or _symbol_from_ticker(ticker) or _asset(sleeve_id),
            "fill_method": "kalshi_paper",
            "ticker": ticker,
            "result": payload.get("result"),
        }
        return "poly_updown_resolution", data

    def _pnl(self, won: bool, vwap: float | None, shares: float | None) -> float:
        if vwap is None or shares is None or shares <= 0:
            # No entry correlation available — best-effort ± half-notional so the
            # win/loss still registers a directionally-correct PnL on the card.
            half = self._notional * 0.5
            return (half - self._fee) if won else (-half - self._fee)
        if won:
            return (1.0 - vwap) * shares - self._fee
        return -vwap * shares - self._fee

    # ------------------------------------------------------------------
    # Async DB write (fire-and-forget)
    # ------------------------------------------------------------------

    def _schedule_insert(self, sleeve_id: str, kind: str, data: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop (sync test context) — nothing to schedule
        loop.create_task(self._insert(sleeve_id, kind, data))

    async def _insert(self, sleeve_id: str, kind: str, data: dict[str, Any]) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, $2, $3::jsonb)",
                    sleeve_id,
                    kind,
                    json.dumps(data),
                )
        except Exception:  # noqa: BLE001 — shadow audit; never crash the loop
            log.warning(
                "kalshi_event_logger.insert_failed", sleeve_id=sleeve_id, kind=kind,
            )


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


__all__ = ["KalshiEventLogger"]
