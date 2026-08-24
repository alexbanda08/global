# Fetch ALL market trades for our 28 round-8 windows via data-api /trades?market=
# (each row carries proxyWallet -> direct same-window pro comparison).
import json, os, time, urllib.request
from collections import defaultdict

DIR = os.path.dirname(os.path.abspath(__file__))
recs = json.load(open(os.path.join(DIR, "..", "wallet_hunt", "cache", "_pm_portfolio",
                                   "0x51a5f36d", "activity_TRADE_2026_08_23a.json")))
NEW = 1787320800
cids = {}
for r in recs:
    slug = r["slug"]
    if slug.startswith("btc-updown-5m-") and int(slug.rsplit("-", 1)[1]) >= NEW:
        cids[slug] = r["conditionId"]
print(f"{len(cids)} windows", flush=True)

out = {}
for slug, cid in sorted(cids.items()):
    rows = []
    for off in range(0, 5000, 500):
        url = f"https://data-api.polymarket.com/trades?market={cid}&limit=500&offset={off}&takerOnly=false"
        for a in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
                batch = json.loads(urllib.request.urlopen(req, timeout=30).read())
                break
            except Exception:
                time.sleep(1.5 * (a + 1))
        else:
            batch = []
        rows.extend(batch)
        if len(batch) < 500:
            break
        time.sleep(0.1)
    out[slug] = rows
    print(slug, len(rows), flush=True)
json.dump(out, open(os.path.join(DIR, "round8_window_trades.json"), "w"))
print("saved", flush=True)
