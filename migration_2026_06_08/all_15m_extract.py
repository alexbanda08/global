"""Extract all 15m resolved shadow fires (BTC/ETH/SOL) per-fire -> CSV for Kalshi candidate search.
Keep asset + offset (Kalshi needs offset>=60, after its +30s book appears)."""
import json, glob, csv
out = []
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-*.jsonl")):
    for line in open(f):
        if "sleeve_fire_resolved" not in line or '"tf":"15m"' not in line.replace(" ", ""):
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("event_type") != "sleeve_fire_resolved" or d.get("tf") != "15m":
            continue
        p = d.get("pnl_usd")
        fu = d.get("fire_us")
        if p is None or not fu:
            continue
        out.append([d.get("sleeve_id"), d.get("asset"), d.get("fire_offset_s"), fu,
                    float(p), 1 if d.get("won") else 0, d.get("fill_vwap"), d.get("slug")])
with open("/tmp/all_15m.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["sid", "asset", "offset", "fire_us", "pnl", "won", "vwap", "slug"])
    w.writerows(out)
print("rows:", len(out))
from collections import Counter
c = Counter((r[1]) for r in out)
print("by asset:", dict(c))
print(len(Counter(r[0] for r in out)), "distinct 15m sleeves")
