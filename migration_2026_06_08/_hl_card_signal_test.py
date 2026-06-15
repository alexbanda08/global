"""
READ-ONLY test: compute the real V52 HL card signal per coin from engine.hl_bars
using the deployed V52 controllers' own signal() logic. No writes, no route change.

Run on vps3:
  set -a; . /etc/tv/tradingvenue.env; set +a
  /opt/tradingvenue/.venv/bin/python _hl_card_signal_test.py "$TV_DB_URL"
"""
from __future__ import annotations
import sys, asyncio
import pandas as pd
import asyncpg

sys.path.insert(0, "/opt/tradingvenue")
from backend.app.controllers.v52 import ALL_V52_CONTROLLERS  # noqa: E402

CARD_COIN = {"V52-BTC": "BTC", "V52-ETH": "ETH", "V52-SOL": "SOL",
             "V52-AVAX": "AVAX", "V52-LINK": "LINK"}


async def load_bars(pool, coin, tf="4h", limit=400):
    rows = await pool.fetch(
        """
        SELECT bar_close_us, open, high, low, close, volume
        FROM engine.hl_bars WHERE symbol=$1 AND tf=$2
        ORDER BY bar_close_us DESC LIMIT $3
        """, coin, tf, limit)
    if not rows:
        return None
    df = pd.DataFrame([dict(r) for r in rows]).iloc[::-1].reset_index(drop=True)
    df.index = pd.to_datetime(df["bar_close_us"].astype("int64"), unit="us", utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df


def card_signal(coin, bars):
    ctrls = [c for c in ALL_V52_CONTROLLERS if getattr(c, "symbol", None) == coin]
    if not ctrls:
        return "FLAT", None, 0, "no_stream"
    net, n, parts = 0, 0, []
    for ctrl in ctrls:
        try:
            intent = ctrl.signal(bars)
            side = intent.side
        except Exception as e:
            side = f"err:{type(e).__name__}"
        parts.append(f"{ctrl.stream_id}={side}")
        if side == "long":
            net += 1
        elif side == "short":
            net -= 1
        n += 1
    direction = "LONG" if net > 0 else "SHORT" if net < 0 else "FLAT"
    conf = round(abs(net) / n, 3) if n else None
    return direction, conf, n, ";".join(parts)


async def main():
    dsn = sys.argv[1]
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        for card, coin in CARD_COIN.items():
            bars = await load_bars(pool, coin)
            if bars is None:
                print(f"{card:9s} coin={coin} NO_BARS")
                continue
            d, conf, n, detail = card_signal(coin, bars)
            print(f"{card:9s} coin={coin} bars={len(bars)} -> {d} conf={conf} n_sleeves={n} | {detail}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
