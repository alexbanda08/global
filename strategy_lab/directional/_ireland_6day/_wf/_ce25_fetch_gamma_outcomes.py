"""Fetch resolution outcomes for 0xce25e214's slugs directly from Polymarket gamma API.
This is more current than vps3 storedata (market_resolutions_v2 has ~50% gaps + no XRP chainlink oracle).
"""
import json
import time
import urllib.request
import urllib.error

SLUGS_PATH = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0xce25e214\_slugs_2026_07_02.txt"
OUT_PATH = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0xce25e214\gamma_outcomes_2026_07_02.json"

with open(SLUGS_PATH) as f:
    slugs = [l.strip() for l in f if l.strip()]

print(f"n slugs: {len(slugs)}")

results = {}
errors = []

for i, slug in enumerate(slugs):
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
    except Exception as e:
        errors.append((slug, str(e)))
        results[slug] = {"error": str(e)}
        continue

    if not d:
        results[slug] = {"found": False}
        continue

    ev = d[0]
    markets = ev.get("markets", [])
    if not markets:
        results[slug] = {"found": True, "no_markets": True}
        continue
    m = markets[0]
    results[slug] = {
        "found": True,
        "closed": m.get("closed"),
        "outcomes": m.get("outcomes"),
        "outcomePrices": m.get("outcomePrices"),
        "umaResolutionStatus": m.get("umaResolutionStatus"),
        "conditionId": m.get("conditionId"),
    }

    if (i + 1) % 25 == 0:
        print(f"  {i+1}/{len(slugs)} fetched, {len(errors)} errors so far")
    time.sleep(0.05)

with open(OUT_PATH, "w") as f:
    json.dump(results, f, indent=1)

print(f"done. {len(results)} results, {len(errors)} errors")
print(f"saved -> {OUT_PATH}")
if errors:
    print("errors:", errors[:10])
