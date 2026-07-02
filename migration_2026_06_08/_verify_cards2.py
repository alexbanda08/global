"""Verify get_signal_current via the ISOLATED own-pool path (does NOT wire
_deps.pool) — simulates the live request when the shared pool is exhausted.

  set -a; . /etc/tv/tradingvenue.env; set +a
  /opt/tradingvenue/.venv/bin/python /tmp/_verify_cards2.py
"""
from __future__ import annotations
import sys, asyncio
sys.path.insert(0, "/opt/tradingvenue")
from backend.app.api import sleeves as S  # noqa: E402


async def main():
    # deliberately do NOT set S._deps.pool — exercise the own-pool path
    for card in ["V52-BTC", "V52-ETH", "V52-SOL", "V52-AVAX", "V52-LINK", "V24-XSM"]:
        try:
            res = await S.get_signal_current(card, None)
            print(f"{card:9s} direction={res.direction:5s} confidence={res.confidence} blocked={res.blocked}")
        except Exception as e:
            print(f"{card:9s} ERROR {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
