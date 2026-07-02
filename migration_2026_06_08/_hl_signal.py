"""HL V52/XSM card signal introspection (replaces the 23-02 stub for HL sleeves).

Computes the real current directional intent per HL card by running the deployed
V52 controllers' own signal() on recent engine.hl_bars, aggregating the per-coin
bundle to a card-level direction + confidence.

ISOLATION (2026-06-16): uses its OWN small asyncpg pool + a 60s TTL cache rather
than the shared tv-api _deps.pool, which is under acquire-timeout pressure. This
keeps the signal cards working independently of the busy write pool and caps DB
load at ~1 query burst / 60s for the whole HL fleet.

Read-only. Defensive: any failure -> caller falls back to the stub.
"""
from __future__ import annotations

import asyncio
import os
import time

import asyncpg
import pandas as pd

from backend.app.controllers.v52 import ALL_V52_CONTROLLERS

_CARD_COIN = {
    "V52-BTC": "BTC", "V52-ETH": "ETH", "V52-SOL": "SOL",
    "V52-AVAX": "AVAX", "V52-LINK": "LINK",
}

_POOL: asyncpg.Pool | None = None
_POOL_LOCK = asyncio.Lock()
_CACHE: dict[str, tuple[str, float | None]] = {}
_CACHE_TS: float = 0.0
_TTL_S = 60.0


async def _get_pool() -> asyncpg.Pool:
    global _POOL
    if _POOL is None:
        async with _POOL_LOCK:
            if _POOL is None:
                dsn = os.environ.get("TV_DB_URL") or os.environ.get("TV_ENGINE_DB_URL")
                _POOL = await asyncpg.create_pool(
                    dsn, min_size=1, max_size=2, command_timeout=10
                )
    return _POOL


def _bars_df(rows) -> pd.DataFrame | None:
    if not rows:
        return None
    df = pd.DataFrame([dict(r) for r in rows]).iloc[::-1].reset_index(drop=True)
    df.index = pd.to_datetime(df["bar_close_us"].astype("int64"), unit="us", utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df


def _card_direction(coin: str, bars: pd.DataFrame) -> tuple[str, float | None]:
    ctrls = [c for c in ALL_V52_CONTROLLERS if getattr(c, "symbol", None) == coin]
    if not ctrls:
        return ("FLAT", None)
    if bars is None or len(bars) < 30:
        return ("FLAT", None)
    net, n = 0, 0
    for ctrl in ctrls:
        try:
            side = ctrl.signal(bars).side
        except Exception:
            side = "flat"
        if side == "long":
            net += 1
        elif side == "short":
            net -= 1
        n += 1
    if n == 0:
        return ("FLAT", None)
    if net > 0:
        return ("LONG", round(net / n, 3))
    if net < 0:
        return ("SHORT", round(abs(net) / n, 3))
    return ("FLAT", 0.0)


async def _refresh_all() -> None:
    global _CACHE, _CACHE_TS
    pool = await _get_pool()
    out: dict[str, tuple[str, float | None]] = {}
    async with pool.acquire() as con:
        for card, coin in _CARD_COIN.items():
            rows = await con.fetch(
                """
                SELECT bar_close_us, open, high, low, close, volume
                FROM engine.hl_bars WHERE symbol = $1 AND tf = '4h'
                ORDER BY bar_close_us DESC LIMIT 400
                """,
                coin,
            )
            out[card] = _card_direction(coin, _bars_df(rows))
    out["V24-XSM"] = ("FLAT", None)  # multifilter needs >100d history; defensively flat
    _CACHE = out
    _CACHE_TS = time.monotonic()


async def compute_hl_signal(sleeve_id: str):
    """Return (direction, confidence) for an HL card, or None to use the stub.

    Uses an isolated pool + 60s cache. Stale-on-error: returns last good value
    (or None) if a refresh fails.
    """
    if sleeve_id not in _CARD_COIN and sleeve_id != "V24-XSM":
        return None
    if (time.monotonic() - _CACHE_TS) > _TTL_S or not _CACHE:
        try:
            await _refresh_all()
        except Exception:
            return _CACHE.get(sleeve_id)  # stale or None
    return _CACHE.get(sleeve_id)
