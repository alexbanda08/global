"""Extract ALL ETH-5m resolved fires (per-fire) from VPS3 shadow logs -> CSV for
diversifier search. One row per fire: sleeve_id, fire_us, pnl, won, vwap, slug."""
import json, glob, csv
out = []
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-*.jsonl")):
    for line in open(f):
        if "sleeve_fire_resolved" not in line or "ETH" not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("event_type") != "sleeve_fire_resolved" or d.get("asset") != "ETH" or d.get("tf") != "5m":
            continue
        p = d.get("pnl_usd")
        fu = d.get("fire_us")
        if p is None or not fu:
            continue
        out.append([d.get("sleeve_id"), fu, float(p), 1 if d.get("won") else 0,
                    d.get("fill_vwap"), d.get("slug")])
with open("/tmp/all_eth5m.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["sid", "fire_us", "pnl", "won", "vwap", "slug"]); w.writerows(out)
print("rows:", len(out))
