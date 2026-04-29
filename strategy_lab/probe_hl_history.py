"""
Probe Hyperliquid kline availability — try several historical windows
to find the actual oldest available bar per coin.
"""
import time, requests
from datetime import datetime, timezone

API = "https://api.hyperliquid.xyz/info"

def probe(coin: str, start_iso: str, end_iso: str, interval: str = "4h"):
    s = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    e = int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    body = {"type":"candleSnapshot",
            "req":{"coin":coin,"interval":interval,"startTime":s,"endTime":e}}
    r = requests.post(API, json=body, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    first_t = datetime.fromtimestamp(int(data[0]["t"])/1000, timezone.utc)
    last_t = datetime.fromtimestamp(int(data[-1]["t"])/1000, timezone.utc)
    return len(data), first_t, last_t

WINDOWS = [
    ("2023-04-01", "2023-05-01", "narrow window April 2023"),
    ("2023-07-01", "2023-08-01", "narrow window July 2023"),
    ("2023-10-01", "2023-11-01", "narrow window Oct 2023"),
    ("2023-12-01", "2024-01-15", "narrow window Dec 2023 + early Jan 2024"),
    ("2024-01-01", "2024-02-01", "narrow window Jan 2024"),
    ("2024-06-01", "2024-07-01", "narrow window June 2024"),
]

for coin in ["BTC", "ETH", "AVAX", "SOL", "LINK"]:
    print(f"\n=== {coin} ===")
    for s, e, label in WINDOWS:
        try:
            res = probe(coin, s, e)
            if res is None:
                print(f"  [{label}]: NO DATA")
            else:
                n, first, last = res
                print(f"  [{label}]: {n} bars  first={first}  last={last}")
        except Exception as ex:
            print(f"  [{label}]: ERR {ex}")
        time.sleep(0.3)

# Also probe daily — might have more history
print("\n\n=== DAILY interval probe (5000 daily = 13.7 years) ===")
for coin in ["BTC", "ETH", "SOL"]:
    res = probe(coin, "2020-01-01", "2026-04-24", interval="1d")
    if res:
        n, first, last = res
        print(f"  {coin} (1d): {n} bars  first={first}  last={last}")
    time.sleep(0.3)
