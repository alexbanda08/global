# Top-up pro-wallet TRADE activity since Aug 21 14:00 UTC (round-8 window set),
# cache tag _2026_08_23a.
import json, os, time, urllib.request

BASE = "https://data-api.polymarket.com/activity"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wallet_hunt",
                    "cache", "_pm_portfolio")
SINCE = 1787320800  # Aug 21 14:00 UTC
WALLETS = {
    "0xb27bc932": "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82",
    "0xb945945d": "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68",
    "0x21d0a97a": "0x21d0a97aac03917e752857a551bbe5103a00e8d7",
    "0x1b58d3de": "0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11",
    "0x095fd7cc": "0x095fd7cc9ddf7110586d1bda3974eccc52155f24",
    "0x74a2b82f": "0x74a2b82f079e12bcc25cd0d479f17979fb62e32f",
}

def key(r):
    return (r.get("transactionHash"), r.get("asset"), r.get("side"),
            int(float(r.get("size") or 0) * 100), r.get("timestamp"))

def fetch(short, wallet):
    seen, out = set(), []
    end_cursor = None
    while True:
        got = 0
        for offset in range(0, 3500, 500):
            url = f"{BASE}?user={wallet}&type=TRADE&limit=500&offset={offset}"
            if end_cursor:
                url += f"&end={end_cursor}"
            for a in range(3):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
                    batch = json.loads(urllib.request.urlopen(req, timeout=30).read())
                    break
                except Exception:
                    time.sleep(2 * (a + 1))
            else:
                batch = []
            if not batch:
                break
            for rec in batch:
                k = key(rec)
                if k not in seen:
                    seen.add(k); out.append(rec); got += 1
            if len(batch) < 500:
                break
            time.sleep(0.12)
        if not out or got == 0:
            break
        oldest = min(r["timestamp"] for r in out)
        if oldest <= SINCE:
            break
        end_cursor = oldest
    out = [r for r in out if r["timestamp"] >= SINCE]
    path = os.path.join(ROOT, short, "activity_TRADE_2026_08_23a.json")
    with open(path, "w") as fh:
        json.dump(out, fh)
    print(short, len(out), flush=True)

for short, w in WALLETS.items():
    fetch(short, w)
