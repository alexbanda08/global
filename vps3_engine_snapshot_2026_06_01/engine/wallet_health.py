"""Wallet balance polling cache (Phase 23 · D-15/D-16/D-17/D-18).

60s polling task that reads HL ``clearinghouseState`` + Polymarket USDC
balance. The ``GET /health/wallets`` endpoint reads from this cache —
it NEVER probes the venue per request (D-16). Likewise, the sleeves
manifest ``mode='live'|'shadow'`` computation (D-13/D-15) reads via
``get_*_balance_usd()``.

Staleness threshold: ``1.5 × poll_interval`` (default 90s). Beyond that,
the balance is flagged stale and the bundle-level live-mode gate (D-15)
treats sleeves in the affected venue's bundles as ``mode='shadow'`` with
``reason='wallet_unknown'``.

CLAUDE inv 8 — this cache uses tv-engine credentials (``hl_client``
imported from ``backend.app.venues.hyperliquid.client``), NOT the
watchdog's independent credentials. The watchdog's HL client lives in
its own process and reads its own encrypted credentials file — the
watchdog's env-var family is NEVER imported by this module.

CLAUDE inv #13 — read-only Storedata: this module does NOT query
``public.*``. Wallet balance is venue-side state, not market data.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# D-16 — wallet balance poll cadence is 60 seconds.
DEFAULT_POLL_INTERVAL_SECONDS: float = 60.0
# 1.5x interval (90s default) before is_*_stale() flips True.
STALE_MULTIPLIER: float = 1.5


class WalletHealthCache:
    """Periodic poller for HL clearinghouseState + Polymarket USDC balance.

    The cache is read by:
      - ``GET /health/wallets`` (per-venue display, D-17)
      - ``GET /sleeves`` mode computation (D-13 truth table — funded gate)

    The cache is written by the ``run()`` coroutine on a fixed cadence
    (default 60s). Each tick is exception-safe: a failure in one venue
    probe does NOT block the other; the previous value is retained;
    the ``is_*_stale()`` flag flips True after ``STALE_MULTIPLIER ×
    interval`` without a successful poll.
    """

    def __init__(
        self,
        *,
        hl_client: Any,
        hl_account_address: str | None,
        poly_balance_reader: Any,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._hl_client = hl_client
        self._hl_account = hl_account_address
        self._poly_reader = poly_balance_reader
        self._interval = poll_interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        # Cached values — None until the first successful poll.
        self._hl_balance_usd: float | None = None
        self._poly_balance_usd: float | None = None
        # time.time() epoch of the last successful poll for each venue.
        # 0.0 means "never" — is_*_stale() returns True until first success.
        self._hl_last_ok: float = 0.0
        self._poly_last_ok: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Polling loop — runs until ``stop()`` is called.

        Calls ``_tick()`` every ``self._interval`` seconds. Uses an
        ``asyncio.Event`` + ``wait_for(timeout=...)`` so ``stop()`` is
        observed promptly without polling the event in a tight loop.
        """
        logger.info(
            "wallet_health.started",
            extra={
                "event": "wallet_health.started",
                "interval_s": self._interval,
            },
        )
        while not self._stop.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._interval
                )
            except asyncio.TimeoutError:
                # Interval elapsed; loop and tick again.
                pass
        logger.info("wallet_health.stopped")

    def stop(self) -> None:
        """Signal the polling loop to exit cleanly. Idempotent."""
        self._stop.set()

    # ------------------------------------------------------------------
    # Tick — exception-safe per-venue probe
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """One poll attempt for HL + Poly. Each probe is independently
        wrapped — a failure in one does NOT block the other. Previous
        value is retained on failure; ``is_*_stale()`` reflects age."""
        # --- HL probe ---
        if self._hl_client is not None and self._hl_account:
            try:
                state = await self._hl_client.get_clearinghouse_state(
                    self._hl_account
                )
                margin = (
                    state.get("marginSummary", {})
                    if isinstance(state, dict)
                    else {}
                )
                # Some HL responses use accountValue, others totalRawUsd.
                # Prefer accountValue (CLAUDE inv 8 — tv-engine credentials).
                value_str = (
                    margin.get("accountValue")
                    or margin.get("totalRawUsd")
                    or "0"
                )
                self._hl_balance_usd = float(value_str)
                self._hl_last_ok = time.time()
            except Exception:  # noqa: BLE001 — defensive: log + retain prev
                logger.warning(
                    "wallet_health.hl_probe_failed",
                    extra={"event": "wallet_health.hl_probe_failed"},
                    exc_info=True,
                )
        # --- Polymarket probe ---
        if self._poly_reader is not None:
            try:
                bal = await self._poly_reader.get_balance_allowance("USDC")
                # CLOB balance reader returns {"balance": "<usd>"} or similar.
                self._poly_balance_usd = float(bal.get("balance", 0))
                self._poly_last_ok = time.time()
            except Exception:  # noqa: BLE001 — defensive
                logger.warning(
                    "wallet_health.poly_probe_failed",
                    extra={"event": "wallet_health.poly_probe_failed"},
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Read API — used by /health/wallets + /sleeves mode computation
    # ------------------------------------------------------------------

    def get_hl_balance_usd(self) -> float | None:
        """Last cached HL clearinghouse balance, or ``None`` if never polled."""
        return self._hl_balance_usd

    def get_poly_balance_usd(self) -> float | None:
        """Last cached Polymarket USDC balance, or ``None`` if never polled."""
        return self._poly_balance_usd

    def is_hl_stale(self) -> bool:
        """True iff the last HL poll is older than 1.5x interval (or never)."""
        if self._hl_last_ok == 0:
            return True
        return (time.time() - self._hl_last_ok) > (
            self._interval * STALE_MULTIPLIER
        )

    def is_poly_stale(self) -> bool:
        """True iff the last Poly poll is older than 1.5x interval (or never)."""
        if self._poly_last_ok == 0:
            return True
        return (time.time() - self._poly_last_ok) > (
            self._interval * STALE_MULTIPLIER
        )

    def hl_age_seconds(self) -> float:
        """Seconds since the last successful HL poll. ``inf`` when never."""
        return (
            time.time() - self._hl_last_ok
            if self._hl_last_ok
            else float("inf")
        )

    def poly_age_seconds(self) -> float:
        """Seconds since the last successful Poly poll. ``inf`` when never."""
        return (
            time.time() - self._poly_last_ok
            if self._poly_last_ok
            else float("inf")
        )


def start_wallet_health_cache(
    *,
    hl_client: Any,
    hl_account_address: str | None,
    poly_balance_reader: Any,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> WalletHealthCache:
    """Construct a ``WalletHealthCache``. Caller schedules ``run()`` on a
    TaskGroup or asyncio.create_task in the lifespan."""
    return WalletHealthCache(
        hl_client=hl_client,
        hl_account_address=hl_account_address,
        poly_balance_reader=poly_balance_reader,
        poll_interval_seconds=poll_interval_seconds,
    )


__all__ = [
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "STALE_MULTIPLIER",
    "WalletHealthCache",
    "start_wallet_health_cache",
]
