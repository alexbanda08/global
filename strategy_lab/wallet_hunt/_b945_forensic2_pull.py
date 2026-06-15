"""
B945 Forensic2 - Task 1: Re-pull freshest trades from data-api.
Paginates TRADE, REDEEM, SPLIT, MERGE, CONVERSION types.
Saves to cache/_pm_portfolio/0xb945945d/activity_{TYPE}_2026_06_13.json
"""
import requests, json, time, os

WALLET = "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68"
OUT_DIR = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d"
BASE_URL = "https://data-api.polymarket.com/activity"
TYPES = ["TRADE", "REDEEM", "SPLIT", "MERGE", "CONVERSION"]

os.makedirs(OUT_DIR, exist_ok=True)

def paginate(activity_type, limit=500):
    records = []
    offset = 0
    while True:
        url = f"{BASE_URL}?user={WALLET}&type={activity_type}&limit={limit}&offset={offset}"
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"  ERROR at offset {offset}: {e}")
            break
        if not batch:
            break
        records.extend(batch)
        print(f"  {activity_type}: fetched {len(records)} (batch={len(batch)})")
        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.3)
    return records

for t in TYPES:
    print(f"\nFetching {t}...")
    recs = paginate(t)
    out_path = f"{OUT_DIR}/activity_{t}_2026_06_13.json"
    with open(out_path, "w") as f:
        json.dump(recs, f)
    print(f"  Saved {len(recs)} records -> {out_path}")

print("\nDone.")
