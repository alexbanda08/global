"""
Fetch all recent trades for 0xb945945d from Polymarket data-api.
Saves to strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/activity_TRADE_2026_06_12.json
"""
import urllib.request
import json
import os
import time
import datetime

USER = "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68"
OUT_DIR = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d"
OUT_FILE = os.path.join(OUT_DIR, "activity_TRADE_2026_06_12.json")

os.makedirs(OUT_DIR, exist_ok=True)

base = f"https://data-api.polymarket.com/activity?user={USER}&type=TRADE&limit=500"

all_trades = []
offset = 0

while True:
    url = base + f"&offset={offset}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"ERROR at offset {offset}: {e}")
        break

    if not data:
        print(f"Empty response at offset {offset}, stopping.")
        break

    all_trades.extend(data)
    print(f"offset={offset:4d} got={len(data):3d} total={len(all_trades):4d}")

    if len(data) < 500:
        break
    offset += 500
    if offset >= 5000:
        print("Hit 5000 hard cap")
        break
    time.sleep(0.2)

print(f"\nTotal trades fetched: {len(all_trades)}")
if all_trades:
    ts_list = [t["timestamp"] for t in all_trades]
    print(f"Newest: {datetime.datetime.utcfromtimestamp(max(ts_list))} UTC  ({max(ts_list)})")
    print(f"Oldest: {datetime.datetime.utcfromtimestamp(min(ts_list))} UTC  ({min(ts_list)})")

with open(OUT_FILE, "w") as f:
    json.dump(all_trades, f, indent=2)
print(f"\nSaved to {OUT_FILE}")
