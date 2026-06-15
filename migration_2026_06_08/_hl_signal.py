"""HL V52/XSM card signal introspection (replaces the 23-02 stub for HL sleeves).

Computes the real current directional intent per HL card by running the deployed
V52 controllers' own signal() on recent engine.hl_bars, then aggregating the
per-coin bundle to a card-level direction + confidence.

Read-only. Defensive: any failure -> caller falls back to the stub.
"""
from __future__ import annotations

import pandas as pd

from backend.app.controllers.v52 import ALL_V52_CONTROLLERS

_CARD_COIN = {
    "V52-BTC": "BTC", "V52-ETH": "ETH", "V52-SOL": "SOL",
    "V52-AVAX": "AVAX", "V52-LINK": "LINK",
}


async def _load_bars(pool, coin: str, tf: str = "4h", limit: int = 400):
    rows = await pool.fetch(
        """
        SELECT bar_close_us, open, high, low, close, volume
        FROM engine.hl_bars WHERE symbol = $1 AND tf = $2
        ORDER BY bar_close_us DESC LIMIT $3
        """,
        coin, tf, limit,
    )
    if not rows:
        return None
    df = pd.DataFrame([dict(r) for r in rows]).iloc[::-1].reset_index(drop=True)
    df.index = pd.to_datetime(df["bar_close_us"].astype("int64"), unit="us", utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df


async def compute_hl_signal(pool, sleeve_id: str):
    """Return (direction, confidence) for an HL card, or None to use the stub.

    direction in {LONG, SHORT, FLAT}; confidence in [0,1] or None.
    """
    if sleeve_id == "V24-XSM":
        # Multi-filter needs >100d MA history not retained in engine.hl_bars;
        # the basket is defensively flat (filter gated off). Honest FLAT.
        return ("FLAT", None)

    coin = _CARD_COIN.get(sleeve_id)
    if coin is None:
        return None  # unknown -> let caller stub it

    ctrls = [c for c in ALL_V52_CONTROLLERS if getattr(c, "symbol", None) == coin]
    if not ctrls:
        return ("FLAT", None)  # no deployed stream for this coin (e.g. BTC)

    bars = await _load_bars(pool, coin)
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
