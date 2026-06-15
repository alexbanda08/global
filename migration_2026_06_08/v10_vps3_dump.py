import json, glob, datetime as dt
from collections import Counter, defaultdict
SID = "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10"
CUT = None  # last 5 full days
ev = Counter()
skip = Counter()
placed = {}      # slug -> dict(dir, fill_vwap, cross_spread, pnl, won, day)
resolved = {}
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-*.jsonl"))[-6:]:
    day = f.split("/")[-1][:10]
    with open(f) as fh:
        for line in fh:
            if "grandparent_V10" not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("sleeve_id") != SID:
                continue
            et = d.get("event_type", "?")
            ev[et] += 1
            if et == "sleeve_fire_eval" and not d.get("all_gates_passed", True):
                skip[str(d.get("skip_reason"))] += 1
            if et == "sleeve_fire_placed":
                snap = d.get("l25_book_snapshot") or {}
                placed[d.get("slug")] = dict(
                    dir=d.get("direction"), vwap=d.get("fill_vwap"),
                    cross=snap.get("cross_spread_old") or snap.get("cross_spread"),
                    bsrc=snap.get("up_book_source"), day=day)
            if et == "sleeve_fire_resolved":
                resolved[d.get("slug")] = dict(dir=d.get("direction"), vwap=d.get("fill_vwap"),
                                               won=d.get("won"), pnl=d.get("pnl_usd"), day=day)

print("VPS3 V10 event_type counts (last ~5d):", dict(ev))
print("placed slugs:", len(placed), " resolved slugs:", len(resolved))
print("top skip_reasons (gates failed):")
for r, c in skip.most_common(12):
    print(f"   {c:5d}  {r}")
# dump placed+resolved slug list for matching
import csv
rows = []
for slug, p in placed.items():
    r = resolved.get(slug, {})
    rows.append([slug, p["dir"], p["vwap"], p.get("cross"), r.get("won"), r.get("pnl"), p["day"]])
with open("/tmp/v10_vps3_placed.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["slug", "dir", "vwap", "cross_spread", "won", "pnl", "day"]); w.writerows(rows)
print("wrote /tmp/v10_vps3_placed.csv", len(rows))
# resolved-only stats
import statistics as st
pn = [r["pnl"] for r in resolved.values() if r.get("pnl") is not None]
wn = [1 for r in resolved.values() if r.get("won")]
if pn:
    print(f"VPS3 resolved: n={len(pn)} WR={sum(wn)/len(pn)*100:.1f}% total=${sum(pn):+.1f} mean=${sum(pn)/len(pn):+.3f}")
