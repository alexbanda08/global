"""
One-shot: backfill 2024 HL 4h bars into engine.hl_bars so fit_regime.py can
train the V52 regime GMM on the canonical D-04 window (2024-01 -> 2024-08).

VPS3's engine.hl_bars has 7-day retention, so the 2024 history needed by the
regime fit isn't present. This pulls it from the HL candleSnapshot REST API and
inserts ON CONFLICT DO NOTHING. Run fit_regime IMMEDIATELY after (before the
retention sweep deletes these old rows again).

Usage (on vps3):
  set -a; . /etc/tv/tradingvenue.env; set +a
  /opt/tradingvenue/.venv/bin/python _hl_2024_backfill.py --dsn "$TV_DB_URL" \
      --start 2024-01-01 --end 2024-08-16
"""
from __future__ import annotations
import argparse, time, sys
from datetime import datetime, timezone, timedelta
import requests
import asyncio
import asyncpg

API = "https://api.hyperliquid.xyz/info"
COINS = ["BTC", "ETH", "AVAX", "SOL", "LINK"]


def _post(body, retries=4, timeout=30):
    last = None
    for a in range(retries):
        try:
            r = requests.post(API, json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1.5 ** a)
    raise last


def fetch_4h(coin, start_dt, end_dt):
    """Walk 30-day windows; dedup by open-time t."""
    rows, seen = [], set()
    cur = start_dt
    step = timedelta(days=30)
    while cur < end_dt:
        ce = min(cur + step, end_dt)
        body = {"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "4h",
            "startTime": int(cur.timestamp() * 1000),
            "endTime": int(ce.timestamp() * 1000)}}
        try:
            data = _post(body) or []
        except Exception as e:
            print(f"  {coin} window {cur:%Y-%m-%d} ERR {type(e).__name__}: {e}", flush=True)
            data = []
        for d in data:
            t = int(d["t"])
            if t not in seen:
                seen.add(t)
                rows.append(d)
        cur = ce
        time.sleep(0.15)
    return rows


async def insert_bars(dsn, coin, rows):
    if not rows:
        return 0
    recs = []
    for d in rows:
        recs.append((
            coin, "4h",
            int(d["t"]) * 1000,            # bar_open_us
            int(d["T"]) * 1000,            # bar_close_us
            float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]),
            float(d["v"]), int(d.get("n", 0)),
        ))
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as con:
            res = await con.executemany(
                """
                INSERT INTO engine.hl_bars
                  (symbol, tf, bar_open_us, bar_close_us, open, high, low, close, volume, trades_count)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (symbol, tf, bar_close_us) DO NOTHING
                """,
                recs,
            )
    finally:
        await pool.close()
    return len(recs)


async def amain(args):
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    total = 0
    for coin in COINS:
        rows = fetch_4h(coin, start, end)
        n = await insert_bars(args.dsn, coin, rows)
        # report min/max
        if rows:
            tmin = datetime.fromtimestamp(min(int(d["t"]) for d in rows) / 1000, timezone.utc)
            tmax = datetime.fromtimestamp(max(int(d["t"]) for d in rows) / 1000, timezone.utc)
            print(f"{coin}: pulled {len(rows)} 4h bars  {tmin:%Y-%m-%d}->{tmax:%Y-%m-%d}  inserted(attempt) {n}", flush=True)
        else:
            print(f"{coin}: NO DATA returned", flush=True)
        total += len(rows)
    print(f"DONE total bars pulled: {total}", flush=True)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", required=True)
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2024-08-16")
    sys.exit(asyncio.run(amain(p.parse_args())))
