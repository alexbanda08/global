"""
Fit V52 regime GMM per coin from engine.hl_bars (2024 window) and write
JSON artifact + engine.v52_regime_models pointer. Reuses the production
regime functions; fixes the str-vs-date asyncpg bug in scripts/v52/fit_regime.py
by passing real date/datetime objects.

Run on vps3:
  set -a; . /etc/tv/tradingvenue.env; set +a
  /opt/tradingvenue/.venv/bin/python _v52_fit.py "$TV_DB_URL" 2024-03-02 2024-08-16
"""
from __future__ import annotations
import sys, asyncio
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np
import asyncpg

sys.path.insert(0, "/opt/tradingvenue")
from backend.app.strategies.v52 import regime  # noqa: E402

COINS = ["BTC", "ETH", "AVAX", "SOL", "LINK"]
OUT_DIR = Path("/var/lib/tradingvenue/v52")


async def fetch_returns(dsn: str, coin: str, start: date, end: date) -> np.ndarray:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        rows = await pool.fetch(
            """
            SELECT close FROM engine.hl_bars
            WHERE symbol = $1 AND tf = '4h'
              AND bar_close_us BETWEEN
                  EXTRACT(EPOCH FROM $2::timestamptz)::bigint * 1000000
              AND EXTRACT(EPOCH FROM $3::timestamptz)::bigint * 1000000
            ORDER BY bar_close_us ASC
            """,
            coin, start, end,
        )
    finally:
        await pool.close()
    closes = np.array([float(r["close"]) for r in rows], dtype=float)
    if len(closes) < 2:
        raise SystemExit(f"Not enough bars for {coin} in [{start},{end}]")
    return np.diff(np.log(closes))


async def write_pointer(dsn, coin, path, payload):
    ts = payload["fit_timestamp"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        await pool.execute(
            """
            INSERT INTO engine.v52_regime_models
              (coin, artifact_path, fit_hash, fit_timestamp, sklearn_version,
               n_components, train_bar_count)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (coin) DO UPDATE
              SET artifact_path=EXCLUDED.artifact_path, fit_hash=EXCLUDED.fit_hash,
                  fit_timestamp=EXCLUDED.fit_timestamp, sklearn_version=EXCLUDED.sklearn_version,
                  n_components=EXCLUDED.n_components, train_bar_count=EXCLUDED.train_bar_count
            """,
            coin, str(path), str(payload["fit_hash"]), ts,
            str(payload["sklearn_version"]), int(payload["n_components"]),
            int(payload["train_bar_count"]),
        )
    finally:
        await pool.close()


async def main():
    dsn, start_s, end_s = sys.argv[1], sys.argv[2], sys.argv[3]
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for coin in COINS:
        rets = await fetch_returns(dsn, coin, start, end)
        out = OUT_DIR / f"regime_{coin}.json"
        gmm = regime.fit_regime(rets, n_components=3)
        payload = regime.save_regime_json(gmm, coin=coin, path=out, train_bar_count=len(rets))
        regime.load_regime_json(out)  # roundtrip smoke
        await write_pointer(dsn, coin, out, payload)
        print(f"{coin}: n_train={len(rets)} hash={str(payload['fit_hash'])[:12]} -> {out}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
