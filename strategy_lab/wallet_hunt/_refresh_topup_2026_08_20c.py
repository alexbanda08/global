"""Round-3 top-up (2026-08-20 afternoon): ours full since Aug-17, refs since 12:00 UTC today."""
import json, os, time, urllib.request

BASE = "https://data-api.polymarket.com/activity"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "_pm_portfolio")

def key(r):
    return (r.get("transactionHash"), r.get("asset"), r.get("side"),
            int(float(r.get("size") or 0) * 100), r.get("timestamp"))

def fetch(wallet, typ, since):
    seen, out = set(), []
    end_cursor = None
    while True:
        got = 0
        for offset in range(0, 3500, 500):
            url = f"{BASE}?user={wallet}&type={typ}&limit=500&offset={offset}"
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
        if oldest <= since:
            break
        end_cursor = oldest
    return [r for r in out if r["timestamp"] >= since]

JOBS = [
    ("0x51a5f36d", "0x51a5f36def5138505975fa2c1a497dc1aa74dd96", 1786924800),  # ours: full since Aug-17
    ("0xb945945d", "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68", 1787230500),  # refs: since Aug-20 12:00
    ("0xb27bc932", "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82", 1787230500),
    ("0x1b58d3de", "0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11", 1787230500),
    ("0x21d0a97a", "0x21d0a97aac03917e752857a551bbe5103a00e8d7", 1787230500),
]
for short, full, since in JOBS:
    outdir = os.path.join(ROOT, short); os.makedirs(outdir, exist_ok=True)
    for typ in ("TRADE", "REDEEM"):
        recs = fetch(full, typ, since)
        json.dump(recs, open(os.path.join(outdir, f"activity_{typ}_2026_08_20c.json"), "w"))
        ts = [r["timestamp"] for r in recs] or [0]
        print(f"{short} {typ}: {len(recs)} [{time.strftime('%m-%d %H:%M', time.gmtime(min(ts)))} .. "
              f"{time.strftime('%m-%d %H:%M', time.gmtime(max(ts)))}]", flush=True)
