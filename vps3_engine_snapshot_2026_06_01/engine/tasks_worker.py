"""tv-engine async task worker — Phase 17.2 SECRETS-UI-03 Task 3.

Picks rows from ``trading.engine_tasks`` with FOR UPDATE SKIP LOCKED,
flips ``status`` to ``broadcast`` BEFORE invoking the chain submit (so a
crash mid-submit leaves an auditable orphan that the operator must
manually cancel — never auto-rebroadcast), then calls
``poly_client.set_max_usdc_allowance()``, waits for N confirmations,
and writes back the tx_hash.

CONTEXT.md D-04 — the signing key NEVER leaves tv-engine. tv-api
ENQUEUES tasks; this worker is the ONLY component that signs.

CLAUDE.md inv #11 — this worker is NOT a trader. It only writes to the
``trading.engine_tasks`` table and submits ERC20 approve txs (NOT
order placements). It cannot trade.

Threat coverage:
  T-17.2-13 — concurrent worker double-pick is prevented via FOR UPDATE
              SKIP LOCKED. Two workers competing for the same row will
              get exactly one row delivered to one worker.
  T-17.2-14 — log lines emit task_id and tx_hash only; never the
              private key (the registry-loaded key never crosses a log
              line in this module).
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)


# Default cadence — overridable in tests via idle_sleep_s.
_DEFAULT_IDLE_SLEEP_SEC = 5.0


# ---------------------------------------------------------------------------
# Internal helper exposed for testability (the FOR UPDATE SKIP LOCKED
# query is the high-risk surface; tests want a direct handle on it).
# ---------------------------------------------------------------------------


async def _pick_one_task(conn: Any) -> Any:
    """Run the FOR UPDATE SKIP LOCKED probe on an open transaction."""
    return await conn.fetchrow(
        "SELECT id, kind, payload FROM trading.engine_tasks "
        "WHERE status='queued' "
        "ORDER BY requested_at ASC FOR UPDATE SKIP LOCKED LIMIT 1"
    )


async def record_engine_boot(
    pool: Any, *, version: str, git_sha: str
) -> None:
    """Insert a row into ``trading.engine_boots`` at lifespan startup.

    tv-api's GET /settings/secrets reads the latest boot timestamp via
    the ``latest_engine_boot_at`` field; without this row the UI's
    "engine restart pending" banner never clears.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO trading.engine_boots (boot_at, version, git_sha) "
            "VALUES (now(), $1, $2)",
            version,
            git_sha,
        )


async def _wait_for_n_confirmations(
    rpc_url: str, tx_hash: str, n: int = 3, *, max_wait_s: float = 300.0
) -> None:
    """Poll eth_getTransactionReceipt until tx has at least n confirmations.

    Raises TimeoutError if the tx has not confirmed within max_wait_s seconds
    (default 5 minutes).  Without a deadline an orphaned or re-org'd tx would
    spin the worker forever, blocking all subsequent Polymarket tasks at $100k+.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wait_s
    while True:
        if loop.time() > deadline:
            raise TimeoutError(
                f"tx {tx_hash} did not reach {n} confirmations within {max_wait_s}s"
            )
        async with httpx.AsyncClient(timeout=10.0) as client:
            receipt_resp = await client.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getTransactionReceipt",
                    "params": [tx_hash],
                },
            )
            block_resp = await client.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "eth_blockNumber",
                    "params": [],
                },
            )
        receipt = receipt_resp.json().get("result")
        latest_block_hex = block_resp.json().get("result")
        if receipt and receipt.get("blockNumber") and latest_block_hex:
            tx_block = int(receipt["blockNumber"], 16)
            latest = int(latest_block_hex, 16)
            if latest - tx_block >= n:
                return
        await asyncio.sleep(2.0)


# ---------------------------------------------------------------------------
# The worker.
# ---------------------------------------------------------------------------


async def _engine_tasks_worker(
    *,
    pool: Any,
    poly_client: Any,
    polygon_rpc_url: str,
    stop: asyncio.Event,
    wait_for_confirmations: Callable[..., Awaitable[None]] | None = None,
    idle_sleep_s: float = _DEFAULT_IDLE_SLEEP_SEC,
) -> None:
    """Pick queued engine_tasks; sign + submit on-chain; update status.

    Args:
      pool: asyncpg.Pool. Required.
      poly_client: PolymarketClient instance constructed with the
        SecretsRegistry (so set_max_usdc_allowance has a signer key).
      polygon_rpc_url: passed to wait_for_confirmations.
      stop: asyncio.Event. Worker exits cleanly when set.
      wait_for_confirmations: injectable for tests; defaults to the
        real eth_getTransactionReceipt poller.
      idle_sleep_s: cadence between empty-queue polls. Defaults to 5s.

    The function never raises; per-task exceptions are caught and the
    row is marked status='failed' with the truncated error text.
    """
    log.info("engine_tasks_worker.starting")
    confirm_fn = wait_for_confirmations or _wait_for_n_confirmations

    while not stop.is_set():
        # Pick + atomic status flip in a single txn.  The status flip
        # to 'broadcast' MUST commit BEFORE the chain submit (T-17.2-13
        # idempotency: a crash mid-submit must leave a 'broadcast' row,
        # NOT a 'queued' row that another worker would re-pick).
        task_row: Any = None
        async with pool.acquire() as conn, conn.transaction():
            task_row = await _pick_one_task(conn)
            if task_row is not None:
                await conn.execute(
                    "UPDATE trading.engine_tasks "
                    "SET status='broadcast', broadcast_at=now() WHERE id=$1",
                    task_row["id"],
                )

        if task_row is None:
            # Queue empty — wait briefly OR until stop fires.
            try:
                await asyncio.wait_for(stop.wait(), timeout=idle_sleep_s)
            except asyncio.TimeoutError:
                pass
            continue

        task_id = task_row["id"]
        kind = task_row["kind"]
        try:
            if kind == "poly_set_max_allowance":
                tx_hash = await poly_client.set_max_usdc_allowance()
                await confirm_fn(polygon_rpc_url, tx_hash, n=3)
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE trading.engine_tasks "
                        "SET status='confirmed', confirmed_at=now(), "
                        "tx_hash=$1 WHERE id=$2",
                        tx_hash,
                        task_id,
                    )
                log.info(
                    "engine_tasks_worker.confirmed",
                    task_id=task_id,
                    tx_hash=tx_hash,
                )
            else:
                raise ValueError(f"unknown task kind: {kind}")
        except Exception as exc:  # noqa: BLE001 — failure path: mark + continue
            err_msg = str(exc)[:500]  # T-17.2-14 — bounded log surface
            log.warning(
                "engine_tasks_worker.failed",
                task_id=task_id,
                kind=kind,
                error_type=type(exc).__name__,
            )
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE trading.engine_tasks "
                        "SET status='failed', error=$1 WHERE id=$2",
                        err_msg,
                        task_id,
                    )
            except Exception:  # noqa: BLE001 — DB write race; log + continue
                log.exception(
                    "engine_tasks_worker.failure_write_race",
                    task_id=task_id,
                )

    log.info("engine_tasks_worker.stopped")


__all__ = [
    "_engine_tasks_worker",
    "_pick_one_task",
    "_wait_for_n_confirmations",
    "record_engine_boot",
]
