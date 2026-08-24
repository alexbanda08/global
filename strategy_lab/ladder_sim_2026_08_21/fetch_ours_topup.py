# Top-up fetch of OUR wallet's TRADE+REDEEM activity since Aug 4 (campaign start),
# cache tag _2026_08_21b, for the guard replay counterfactual.
import json, os, time, urllib.request

BASE = "https://data-api.polymarket.com/activity"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wallet_hunt",
                    "cache", "_pm_portfolio", "0x51a5f36d")
WALLET = "0x51a5f36def5138505975fa2c1a497dc1aa74dd96"
SINCE = 1785801600  # Aug 4 00:00 UTC

def key(r):
    return (r.get("transactionHash"), r.get("asset"), r.get("side"),
            int(float(r.get("size") or 0) * 100), r.get("timestamp"))

def fetch(typ):
    seen, out = set(), []
    end_cursor = None
    while True:
        got = 0
        for offset in range(0, 3500, 500):
            url = f"{BASE}?user={WALLET}&type={typ}&limit=500&offset={offset}"
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
    path = os.path.join(ROOT, f"activity_{typ}_2026_08_24a.json")
    with open(path, "w") as fh:
        json.dump(out, fh)
    print(typ, len(out), "->", path, flush=True)

for t in ("TRADE", "REDEEM", "MERGE"):
    fetch(t)
