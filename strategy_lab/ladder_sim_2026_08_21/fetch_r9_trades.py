# Fetch full per-market tape for the 66 round-9 windows (deep offsets, incremental save).
import json, os, time, urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
recs = json.load(open(os.path.join(DIR, "..", "wallet_hunt", "cache", "_pm_portfolio",
                                   "0x51a5f36d", "activity_TRADE_2026_08_24a.json")))
NEW = 1787492400
cids = {}
for r in recs:
    slug = r["slug"]
    if slug.startswith("btc-updown-5m-") and int(slug.rsplit("-", 1)[1]) > NEW:
        cids[slug] = r["conditionId"]
OUT = os.path.join(DIR, "round9_window_trades.json")
data = json.load(open(OUT)) if os.path.exists(OUT) else {}
print(f"{len(cids)} windows, {len(data)} cached", flush=True)
for slug, cid in sorted(cids.items()):
    if slug in data:
        continue
    rows = []
    for off in range(0, 8000, 500):
        url = f"https://data-api.polymarket.com/trades?market={cid}&limit=500&offset={off}&takerOnly=false"
        for a in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
                batch = json.loads(urllib.request.urlopen(req, timeout=25).read())
                break
            except Exception:
                time.sleep(1.2 * (a + 1))
        else:
            batch = []
        rows.extend(batch)
        if len(batch) < 500:
            break
        time.sleep(0.05)
    data[slug] = rows
    json.dump(data, open(OUT, "w"))
    print(slug, len(rows), flush=True)
print("done", flush=True)
