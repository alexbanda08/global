"""BookMirror — TV-native Polymarket WS book mirror (Phase 18.6 Wave 1).

Tier-1 hot-path read source. Owns a single multiplexed WS connection to
``wss://ws-subscriptions-clob.polymarket.com/ws/market`` and maintains an
in-memory L25 mirror of every subscribed token's book. Used by both
``PolyPaperExecutor`` (paper) and ``PolymarketClient.get_orderbook_snapshot``
(live) so the hot-path read source is identical between modes.

Architecture (per Phase 18.6 CONTEXT §3-tier):
    Tier 1 (this module): WS BookMirror, <10ms staleness, owned by tv-engine
    Tier 2: CLOB HTTP /book (boot-warmup + reconciler)
    Tier 3: Storedata `public.orderbook_snapshots_v2` (disaster fallback,
            emits critical alert when it answers)

CLAUDE.md inv #13: hot-path reads MUST come from TV-direct venue
connections, not from Storedata. This class IS the TV-direct path for
Polymarket. Storedata-fallback-as-primary is FORBIDDEN for live mode.

Lifecycle:
    mirror = BookMirror(alert_service=alerts)
    await mirror.start()                # opens WS, starts reader + heartbeat
    await mirror.subscribe(token_id)    # adds to active set + WS sub msg
    book = mirror.get(token_id)         # in-memory L25 read, <1ms
    await mirror.unsubscribe(token_id)  # removes from active set
    await mirror.stop()                 # clean WS close, cancel tasks

Reconnect: exponential backoff (1, 2, 4, 8, 16, 30s capped). On reconnect,
full re-subscribe of all known active tokens. The ``websockets`` library
manages low-level TCP/TLS reconnect under the hood; we layer protocol-level
re-subscribe on top.

Heartbeat: ``websockets`` library's built-in ping/pong (ping_interval=30s,
ping_timeout=10s) handles the keepalive. On pong timeout the library raises
ConnectionClosed which our reader loop catches and triggers reconnect.

Refcount: subscribe()/unsubscribe() are refcounted so two slots sharing the
same opposite token only send one server-side subscription.

Failure modes:
- WS dead but reconnect succeeding: Tier-2 (CLOB) covers; no alert.
- WS dead AND reconnect failing >5min: WARNING alert.
- A subscribed token returning None on get(): Tier-2 covers; logged at INFO.
- Tier-3 (Storedata) answering: critical alert via alert_service.

Memory: ~5KB per token (25 levels × 2 sides × ~100 bytes Python overhead).
Even with 100 active tokens that's <1MB.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import OrderedDict
from decimal import Decimal
from typing import Any, Literal

import structlog

try:
    import websockets
    from websockets.client import WebSocketClientProtocol
    from websockets.exceptions import ConnectionClosed, WebSocketException
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]
    WebSocketClientProtocol = Any  # type: ignore[misc,assignment]
    ConnectionClosed = Exception  # type: ignore[misc,assignment]
    WebSocketException = Exception  # type: ignore[misc,assignment]


log = structlog.get_logger("backend.app.venues.polymarket.book_mirror")


# Polymarket public market WS — no auth.
DEFAULT_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Reconnect schedule.
RECONNECT_BACKOFF_INITIAL_S = 1.0
RECONNECT_BACKOFF_MAX_S = 30.0

# Heartbeat / liveness — handed to websockets.connect().
WS_PING_INTERVAL_S = 30.0
WS_PING_TIMEOUT_S = 10.0

# Reconnect-failure alert threshold — emit WARNING after this much sustained
# disconnect time (in seconds). Tier-2 (CLOB) covers reads in the meantime,
# but if WS is dead for >5min it indicates a real upstream problem.
RECONNECT_FAILURE_ALERT_S = 300.0


class BookMirror:
    """Live L1-L25 book mirror via Polymarket WS market channel.

    One WS connection (``DEFAULT_WS_URL``), multiplexed across all subscribed
    token_ids. ``get(token_id)`` returns the current book (<1ms in-memory
    read) or None if not subscribed.

    Public API (all coroutines except ``get``):
        - start() / stop()           — lifecycle
        - subscribe(token_id)        — add to active set (refcounted)
        - unsubscribe(token_id)      — remove from active set (refcounted)
        - get(token_id) -> dict|None — read current book

    Returned book shape (matches PolyPaperExecutor._fetch_orderbook):
        {bids: [{price, size}], asks: [{price, size}], ts: int}

    Bids sorted descending (best/highest first). Asks sorted ascending
    (best/lowest first). Same shape as the CLOB and Storedata paths so
    callers can swap tiers transparently.
    """

    def __init__(
        self,
        ws_url: str = DEFAULT_WS_URL,
        *,
        alert_service: Any | None = None,
        ping_interval_s: float = WS_PING_INTERVAL_S,
        ping_timeout_s: float = WS_PING_TIMEOUT_S,
        reconnect_backoff_initial_s: float = RECONNECT_BACKOFF_INITIAL_S,
        reconnect_backoff_max_s: float = RECONNECT_BACKOFF_MAX_S,
        reconnect_failure_alert_s: float = RECONNECT_FAILURE_ALERT_S,
        redis_client: Any | None = None,
    ) -> None:
        if websockets is None:  # pragma: no cover
            raise RuntimeError(
                "websockets library not installed; required for BookMirror"
            )
        self._ws_url = ws_url
        self._alert_service = alert_service
        self._ping_interval_s = ping_interval_s
        self._ping_timeout_s = ping_timeout_s
        self._reconnect_initial_s = reconnect_backoff_initial_s
        self._reconnect_max_s = reconnect_backoff_max_s
        self._reconnect_failure_alert_s = reconnect_failure_alert_s
        # Phase 28.1: Redis bridge to tv-api's /sleeves/{id}/book-health.
        # When set, every book update writes `tv:book:{token_id}` with 30s
        # TTL. Fire-and-forget — Redis errors are logged but never raise
        # so the live book-cache path stays untouched (CONTEXT D-04).
        self._redis_client = redis_client

        # token_id (str) -> {"bids": [...], "asks": [...], "ts": int}
        self._books: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # token_id (str) -> active subscription refcount
        self._refcount: dict[str, int] = {}
        # token_id (str) -> wall-time of last book/price_change update
        self._last_update: dict[str, float] = {}

        # Lifecycle
        self._ws: WebSocketClientProtocol | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._send_lock = asyncio.Lock()

        # Reconnect bookkeeping
        self._first_disconnect_at: float | None = None
        self._connect_attempts: int = 0
        self._connect_successes: int = 0
        self._reconnect_alert_sent: bool = False

    # ------------- public API -------------

    async def start(self) -> None:
        """Open WS connection + start reader loop. Idempotent."""
        if self._reader_task is not None:
            return
        self._stop_event.clear()
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="book_mirror.reader"
        )
        log.info("book_mirror.starting", ws_url=self._ws_url)

    async def stop(self) -> None:
        """Close WS + cancel reader. Idempotent."""
        self._stop_event.set()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
            self._reader_task = None
        self._ws = None
        self._connected_event.clear()
        log.info("book_mirror.stopped")

    async def subscribe(self, token_id: str) -> None:
        """Add token to active set. Refcounted; first add sends WS sub msg."""
        token_id = str(token_id)
        prev = self._refcount.get(token_id, 0)
        self._refcount[token_id] = prev + 1
        if prev > 0:
            return  # already subscribed
        # Wait for first connect (bounded; if not connected yet, the
        # reconnect path will re-subscribe all known tokens on connect).
        if self._connected_event.is_set():
            await self._send_subscribe([token_id])
        log.info(
            "book_mirror.subscribe",
            token_id=token_id,
            refcount=self._refcount[token_id],
            connected=self._connected_event.is_set(),
        )

    async def unsubscribe(self, token_id: str) -> None:
        """Decrement refcount; on zero, drop local state."""
        token_id = str(token_id)
        prev = self._refcount.get(token_id, 0)
        if prev == 0:
            return
        new = prev - 1
        if new > 0:
            self._refcount[token_id] = new
            return
        # Refcount hit zero; drop state. We do NOT send an explicit
        # unsubscribe message because Polymarket WS doesn't support
        # per-token unsubscribe on the market channel; the next reconnect
        # naturally drops it from the re-subscribe set.
        self._refcount.pop(token_id, None)
        self._books.pop(token_id, None)
        self._last_update.pop(token_id, None)
        log.info("book_mirror.unsubscribe", token_id=token_id)

    def get(self, token_id: str) -> dict[str, Any] | None:
        """Return current book for token_id, or None if not tracked.

        None signals "not subscribed". An empty book ``{bids: [], asks: [],
        ts: ...}`` signals "subscribed but no liquidity right now".
        Callers MUST distinguish these — None routes to Tier-2 fallback;
        empty signals real no-liquidity and is reported up.
        """
        token_id = str(token_id)
        if token_id not in self._refcount:
            return None
        book = self._books.get(token_id)
        if book is None:
            # Subscribed but no snapshot received yet (gap between
            # subscribe-sent and first book msg). Return None so the
            # caller falls through to Tier-2.
            return None
        # Defensive copy so caller can't mutate our internal state.
        return {
            "bids": [dict(lvl) for lvl in book.get("bids", [])],
            "asks": [dict(lvl) for lvl in book.get("asks", [])],
            "ts": book.get("ts", 0),
        }

    # ------------- introspection -------------

    @property
    def connected(self) -> bool:
        return self._connected_event.is_set()

    @property
    def active_token_ids(self) -> list[str]:
        return list(self._refcount.keys())

    def stats(self) -> dict[str, Any]:
        """Snapshot of current state for telemetry."""
        return {
            "connected": self.connected,
            "active_subscriptions": len(self._refcount),
            "books_with_data": len(self._books),
            "connect_attempts": self._connect_attempts,
            "connect_successes": self._connect_successes,
        }

    # ------------- internal: connect + reader -------------

    async def _reader_loop(self) -> None:
        """Connect → consume messages → reconnect on close. Forever until stop."""
        backoff = self._reconnect_initial_s
        while not self._stop_event.is_set():
            self._connect_attempts += 1
            try:
                async with websockets.connect(  # type: ignore[union-attr]
                    self._ws_url,
                    ping_interval=self._ping_interval_s,
                    ping_timeout=self._ping_timeout_s,
                    max_size=2**20,  # 1MB per msg cap; orderbook snaps fit.
                    open_timeout=10.0,
                    close_timeout=5.0,
                ) as ws:
                    self._ws = ws
                    self._connected_event.set()
                    self._connect_successes += 1
                    self._first_disconnect_at = None
                    self._reconnect_alert_sent = False
                    backoff = self._reconnect_initial_s
                    log.info(
                        "book_mirror.connected",
                        active_subs=len(self._refcount),
                        successes=self._connect_successes,
                    )
                    # Re-subscribe everything we know about with the
                    # initial-subscribe shape (replaces server's prior set).
                    if self._refcount:
                        await self._send_subscribe(
                            list(self._refcount.keys()), initial=True
                        )
                    # Consume forever until the connection drops.
                    async for raw in ws:
                        try:
                            self._dispatch(raw)
                        except Exception as exc:  # noqa: BLE001
                            log.warning(
                                "book_mirror.dispatch_error",
                                err=str(exc),
                                preview=str(raw)[:200],
                            )
            except (TimeoutError, ConnectionClosed, WebSocketException, OSError) as exc:
                if self._stop_event.is_set():
                    break
                self._connected_event.clear()
                self._ws = None
                if self._first_disconnect_at is None:
                    self._first_disconnect_at = time.time()
                disconnect_age = time.time() - self._first_disconnect_at
                log.warning(
                    "book_mirror.disconnected",
                    err=str(exc),
                    backoff_s=backoff,
                    disconnect_age_s=int(disconnect_age),
                )
                # Sustained disconnect → operator alert (one-shot).
                if (
                    not self._reconnect_alert_sent
                    and disconnect_age > self._reconnect_failure_alert_s
                    and self._alert_service is not None
                ):
                    with contextlib.suppress(Exception):
                        await self._alert_service.emit(
                            severity="warning",
                            kind="poly_book_mirror_reconnect_failing",
                            summary=(
                                f"Polymarket BookMirror disconnected for "
                                f"{int(disconnect_age)}s; Tier-2 (CLOB) is "
                                f"covering reads but hot-path is degraded."
                            ),
                        )
                    self._reconnect_alert_sent = True
                # Sleep with stop-aware wait so stop() doesn't have to wait
                # the full backoff window.
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break  # stop signalled during sleep
                except TimeoutError:
                    pass
                backoff = min(backoff * 2.0, self._reconnect_max_s)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — defensive: never let reader die silently
                log.error(
                    "book_mirror.reader_unexpected_error",
                    err=str(exc),
                    backoff_s=backoff,
                )
                self._connected_event.clear()
                self._ws = None
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break
                except TimeoutError:
                    pass
                backoff = min(backoff * 2.0, self._reconnect_max_s)

    async def _send_subscribe(
        self, token_ids: list[str], *, initial: bool = False
    ) -> None:
        """Send a market subscribe message for the listed token_ids.

        Polymarket WS protocol (verified 2026-05-06 against the working
        Storedata collector at ``/opt/storedata/src/storedata/collectors/polymarket.py``):

          - Initial subscribe (on (re)connect): ``{"assets_ids": [...],
            "type": "market", "custom_feature_enabled": True}``
            Sets the FULL subscription set; replaces any prior set.
          - Incremental subscribe (already connected, adding new token):
            ``{"assets_ids": [...], "operation": "subscribe"}``
            Adds the listed tokens to the existing set.

        Note: ``"type": "market"`` is LOWERCASE; uppercase "MARKET" is
        rejected by the server with text "INVALID OPERATION" (verified
        2026-05-06 in production logs before fix).

        The server responds with a ``book`` snapshot for each requested
        token within ~50-200ms.
        """
        if self._ws is None or not self._connected_event.is_set():
            return  # connect path will pick this up via resubscribe-on-connect
        if initial:
            msg = json.dumps(
                {
                    "assets_ids": token_ids,
                    "type": "market",
                    "custom_feature_enabled": True,
                }
            )
        else:
            msg = json.dumps(
                {"assets_ids": token_ids, "operation": "subscribe"}
            )
        async with self._send_lock:
            try:
                await self._ws.send(msg)
                log.info(
                    "book_mirror.sent_subscribe",
                    count=len(token_ids),
                    initial=initial,
                )
            except (ConnectionClosed, WebSocketException) as exc:
                log.warning(
                    "book_mirror.send_subscribe_failed",
                    err=str(exc),
                    count=len(token_ids),
                )

    # ------------- internal: message dispatch -------------

    def _dispatch(self, raw: str | bytes) -> None:
        """Parse a single WS frame and apply to in-memory book state."""
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("book_mirror.json_decode_failed", preview=str(raw)[:200])
            return
        # Polymarket sends arrays of events sometimes; normalize to list.
        events = payload if isinstance(payload, list) else [payload]
        for evt in events:
            if not isinstance(evt, dict):
                continue
            etype = evt.get("event_type") or evt.get("type")
            if etype == "book":
                self._apply_book_snapshot(evt)
            elif etype == "price_change":
                self._apply_price_change(evt)
            elif etype == "tick_size_change":
                # Rare — log but no state change needed for book reads.
                log.info(
                    "book_mirror.tick_size_change",
                    asset_id=evt.get("asset_id"),
                    new_tick_size=evt.get("new_tick_size"),
                )
            # else: ignore unknown event types defensively.

    def _apply_book_snapshot(self, evt: dict[str, Any]) -> None:
        """Replace local L25 book for this token with the incoming snapshot."""
        token_id = str(evt.get("asset_id", ""))
        if not token_id or token_id not in self._refcount:
            return
        bids = _parse_levels(evt.get("bids"))
        asks = _parse_levels(evt.get("asks"))
        # Best-first sort regardless of server order.
        bids.sort(key=lambda lvl: Decimal(lvl["price"]), reverse=True)
        asks.sort(key=lambda lvl: Decimal(lvl["price"]))
        self._books[token_id] = {
            "bids": bids,
            "asks": asks,
            # IMPORTANT: ts is MILLISECONDS. compute_book_health (engine/
            # microstructure.py:200) reads `as_of_ms = int(snapshot["ts"])`
            # and sleeves.py:2260 compares against `now_ms = int(time.time()*1000)`.
            # Pre-fix wrote seconds -> now_ms - as_of_ms was ~1.78e12 ms,
            # always > 5000 -> stale=true permanently. Tile showed STALE
            # label even on fresh books.
            "ts": int(time.time() * 1000),
        }
        self._last_update[token_id] = time.time()
        # Phase 28.1: publish to Redis bridge for tv-api's /book-health
        # endpoint. Schedule fire-and-forget so the synchronous WS message
        # handler isn't blocked on network I/O.
        if self._redis_client is not None:
            asyncio.create_task(self._publish_to_redis(token_id))

    def _apply_price_change(self, evt: dict[str, Any]) -> None:
        """Apply an incremental price_change message to the in-memory book.

        Polymarket price_change shape (verified vs public docs):
            {event_type: "price_change", asset_id: "...", market: "...",
             changes: [{price: "0.55", side: "BUY"|"SELL", size: "10"}, ...]}

        ``side="BUY"`` updates the bid book; ``side="SELL"`` updates the ask.
        ``size="0"`` removes the level. Otherwise replace level at that price.
        """
        token_id = str(evt.get("asset_id", ""))
        if not token_id or token_id not in self._refcount:
            return
        book = self._books.get(token_id)
        if book is None:
            # No snapshot received yet — defer; the next book event will
            # establish state. price_change deltas are advisory until
            # the snapshot lands.
            return
        changes = evt.get("changes") or []
        if not isinstance(changes, list):
            return
        bids = book["bids"]
        asks = book["asks"]
        for ch in changes:
            if not isinstance(ch, dict):
                continue
            try:
                price_d = Decimal(str(ch.get("price", "0")))
                size_d = Decimal(str(ch.get("size", "0")))
            except Exception:  # noqa: BLE001
                continue
            side = str(ch.get("side", "")).upper()
            if side == "BUY":
                _apply_change(bids, price_d, size_d, side="bid")
            elif side == "SELL":
                _apply_change(asks, price_d, size_d, side="ask")
            # Unknown side: skip.
        # See comment at line ~466 — ts is MILLISECONDS, not seconds.
        book["ts"] = int(time.time() * 1000)
        self._last_update[token_id] = time.time()
        # Phase 28.1: same Redis publish as snapshot path.
        if self._redis_client is not None:
            asyncio.create_task(self._publish_to_redis(token_id))

    async def _publish_to_redis(self, token_id: str) -> None:
        """Phase 28.1: bridge book snapshot to tv-api via Redis SET/GET.

        Writes `tv:book:{token_id}` = json(book) with 30s TTL. Engine has
        already updated `self._books[token_id]` before this is called, so
        we serialize the same dict that `get()` would return.

        Fire-and-forget — Redis errors are logged but never raised so a
        Redis outage cannot break the in-memory book cache or the WS
        reader. Operator sees the gap via the tv-api side's 503 response
        on /book-health.
        """
        if self._redis_client is None:
            return
        book = self._books.get(token_id)
        if book is None:
            return
        try:
            payload = json.dumps(book)
        except (TypeError, ValueError) as e:  # pragma: no cover — books are stringly-typed
            log.warning(
                "book_mirror.redis_serialize_failed",
                token_id=token_id,
                error=str(e),
            )
            return
        try:
            # ex=30 — TTL well above the dashboard's 5s stale threshold,
            # so stale keys auto-expire if the engine stops publishing.
            await self._redis_client.set(
                f"tv:book:{token_id}",
                payload,
                ex=30,
            )
        except Exception as e:  # noqa: BLE001 — defensive: any redis error swallowed
            log.warning(
                "book_mirror.redis_publish_failed",
                token_id=token_id,
                error=str(e),
            )


# ------------- helpers -------------


def _parse_levels(rows: Any) -> list[dict[str, str]]:
    """Convert raw level rows into [{price, size}, ...] string-typed.

    Same shape as PolyPaperExecutor._parse_levels — defensively drops any
    row missing price or size or with non-positive values.
    """
    out: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            px = Decimal(str(r.get("price", "0")))
            sz = Decimal(str(r.get("size", "0")))
        except Exception:  # noqa: BLE001
            continue
        if px <= 0 or sz <= 0:
            continue
        out.append({"price": str(px), "size": str(sz)})
    return out


def _apply_change(
    levels: list[dict[str, str]],
    price: Decimal,
    size: Decimal,
    *,
    side: Literal["bid", "ask"],
) -> None:
    """In-place: replace level at ``price`` with new ``size``, or remove if size=0.

    ``levels`` MUST be pre-sorted (bids descending, asks ascending). We
    preserve that ordering by either updating-in-place or insorting at the
    correct position.
    """
    price_str = str(price)
    # Find existing level at this exact price.
    for i, lvl in enumerate(levels):
        try:
            if Decimal(lvl["price"]) == price:
                if size <= 0:
                    levels.pop(i)
                else:
                    lvl["size"] = str(size)
                return
        except Exception:  # noqa: BLE001
            continue
    # Not present — add if size > 0.
    if size <= 0:
        return
    new_lvl = {"price": price_str, "size": str(size)}
    if side == "bid":
        # Descending sort — insert before first lvl with price < ours.
        for i, lvl in enumerate(levels):
            try:
                if Decimal(lvl["price"]) < price:
                    levels.insert(i, new_lvl)
                    return
            except Exception:  # noqa: BLE001
                continue
        levels.append(new_lvl)
    else:
        # Ascending sort — insert before first lvl with price > ours.
        for i, lvl in enumerate(levels):
            try:
                if Decimal(lvl["price"]) > price:
                    levels.insert(i, new_lvl)
                    return
            except Exception:  # noqa: BLE001
                continue
        levels.append(new_lvl)


__all__ = [
    "BookMirror",
    "DEFAULT_WS_URL",
    "RECONNECT_BACKOFF_INITIAL_S",
    "RECONNECT_BACKOFF_MAX_S",
    "WS_PING_INTERVAL_S",
    "WS_PING_TIMEOUT_S",
]
