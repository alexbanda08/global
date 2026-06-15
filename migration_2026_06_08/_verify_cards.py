"""In-process verification: wire _deps.pool and call the patched
get_signal_current for each HL card. Prints the exact SignalCard payload the
dashboard now receives. Read-only.

Run on vps3:
  set -a; . /etc/tv/tradingvenue.env; set +a
  /opt/tradingvenue/.venv/bin/python /tmp/_verify_cards.py "$TV_DB_URL"
"""
from __future__ import annotations
import sys, asyncio
sys.path.insert(0, "/opt/tradingvenue")
import asyncpg
from backend.app.api import sleeves as S


async def main():
    dsn = sys.argv[1]
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    S._deps.pool = pool  # wire the dependency the endpoint reads
    try:
        for card in ["V52-BTC", "V52-ETH", "V52-SOL", "V52-AVAX", "V52-LINK", "V24-XSM"]:
            try:
                res = await S.get_signal_current(card, None)
                print(f"{card:9s} direction={res.direction:5s} confidence={res.confidence} "
                      f"blocked={res.blocked} reason={res.block_reason}")
            except Exception as e:
                print(f"{card:9s} ERROR {type(e).__name__}: {e}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
