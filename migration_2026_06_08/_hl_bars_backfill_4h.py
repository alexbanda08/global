"""Backfill engine.hl_bars with deep 4h (+1d) history from the Hyperliquid API.

Why: the 7-day blanket retention had left engine.hl_bars with 42 rows at tf='4h',
which silently flattened every V52 sleeve signal (EMA200 needs 200 bars, the
ATR_NOTOPVOL gate a 500-bar percentile rank, the HMM regime fit >=200 train bars).
_patch_hl_retention.py now protects 1h/4h/1d for 400 days; this fills the history
that was already deleted.

ON CONFLICT DO NOTHING on (symbol, tf, bar_close_us) so it is safe to re-run and
cannot disturb rows the live persistence loop is writing.

Run on vps3:
  set -a; . /etc/tv/tradingvenue.env; set +a
  sudo -u tv /opt/tradingvenue/.venv/bin/python /tmp/_hl_bars_backfill_4h.py
"""
from __future__ import annotations
import asyncio, json, os, sys, time, urllib.request
from datetime import datetime, timezone

import asyncpg

API = "https://api.hyperliquid.xyz/info"
COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK"]
TFS = {"4h": 4 * 3600 * 1000, "1d": 24 * 3600 * 1000}
MAX_CANDLES = 5000


def post(body: dict, retries: int = 3):
    data = json.dumps(body).encode()
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(API, data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:  # transient API/network
            last = e
            time.sleep(1.5)
    raise RuntimeError(f"HL API failed: {last}")


async def main() -> int:
    dsn = os.environ.get("TV_DB_URL") or os.environ.get("TV_ENGINE_DB_URL")
    if not dsn:
        print("no TV_DB_URL in env"); return 2
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    conn = await asyncpg.connect(dsn)
    try:
        for tf, step in TFS.items():
            start = now_ms - MAX_CANDLES * step
            for coin in COINS:
                rows = post({"type": "candleSnapshot",
                             "req": {"coin": coin, "interval": tf,
                                     "startTime": start, "endTime": now_ms}})
                if not rows:
                    print(f"{coin:5s} {tf:3s} EMPTY"); continue
                recs = [(coin, tf, int(c["t"]) * 1000, int(c["T"]) * 1000,
                         float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]),
                         float(c["v"]), int(c.get("n", 0)),
                         datetime.now(timezone.utc))
                        for c in rows]
                before = await conn.fetchval(
                    "SELECT count(*) FROM engine.hl_bars WHERE symbol=$1 AND tf=$2", coin, tf)
                await conn.executemany(
                    """INSERT INTO engine.hl_bars
                       (symbol, tf, bar_open_us, bar_close_us, open, high, low, close,
                        volume, trades_count, ingested_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                       ON CONFLICT (symbol, tf, bar_close_us) DO NOTHING""", recs)
                after = await conn.fetchval(
                    "SELECT count(*) FROM engine.hl_bars WHERE symbol=$1 AND tf=$2", coin, tf)
                oldest = await conn.fetchval(
                    "SELECT to_timestamp(min(bar_close_us)/1000000)::date FROM engine.hl_bars "
                    "WHERE symbol=$1 AND tf=$2", coin, tf)
                print(f"{coin:5s} {tf:3s} api={len(recs):5d}  rows {before:5d} -> {after:5d}  oldest={oldest}")
                time.sleep(0.25)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
