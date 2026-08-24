"""R0 — probe whether the HL API can serve the 2023-05 -> 2024-02 hole in our 4h store."""
from __future__ import annotations
import sys, time
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from strategy_lab.ingest_hyperliquid import post_info

MS = 1000


def probe(coin: str, ymd: str, interval: str = "4h"):
    t0 = int(datetime.fromisoformat(ymd + "T00:00:00+00:00").timestamp() * MS)
    t1 = t0 + 20 * 86400 * MS
    body = {"type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": t0, "endTime": t1}}
    try:
        d = post_info(body)
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"
    if not d:
        return "EMPTY"
    f = datetime.fromtimestamp(int(d[0]["t"]) / MS, timezone.utc)
    l = datetime.fromtimestamp(int(d[-1]["t"]) / MS, timezone.utc)
    return f"n={len(d):4d} {f:%Y-%m-%d} -> {l:%Y-%m-%d}"


if __name__ == "__main__":
    for coin in ["BTC", "ETH"]:
        for ymd in ["2023-05-01", "2023-07-01", "2023-10-01", "2024-01-01", "2024-02-15", "2024-03-01"]:
            print(f"{coin:5s} {ymd}: {probe(coin, ymd)}")
            time.sleep(0.3)
