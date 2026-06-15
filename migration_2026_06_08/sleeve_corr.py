"""Compare exact fires of candidate ETH-5m sleeves: slug overlap (Jaccard), direction
agreement on common slugs, and daily-PnL correlation (which diversify / are uncorrelated)."""
import json, glob, math
from collections import defaultdict

DAY = 86_400_000_000
SLEEVES = {
    "v6c3_parent15mrang_v7": "poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7",
    "cloud_ribbon_V10": "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10",
    "cloud_vwap_v7": "poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7",
    "cloud_ribbon_v6": "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6",
}
ID2TAG = {v: k for k, v in SLEEVES.items()}

# slug -> {tag: (direction, pnl)} ; tag -> {day: pnl}
fires = defaultdict(dict)
daily = defaultdict(lambda: defaultdict(float))
maxf = 0
recs = []
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-06-0[4-9].jsonl")):
    for line in open(f):
        if "sleeve_fire_resolved" not in line:
            continue
        hit = False
        for sid in SLEEVES.values():
            if sid in line:
                hit = True; break
        if not hit:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("sleeve_id") not in ID2TAG or d.get("event_type") != "sleeve_fire_resolved":
            continue
        recs.append(d); maxf = max(maxf, d.get("fire_us", 0))
win_lo = maxf - 5 * DAY
import datetime as dt
for d in recs:
    fu = d.get("fire_us", 0)
    if fu < win_lo:
        continue
    tag = ID2TAG[d["sleeve_id"]]
    slug = d.get("slug")
    p = float(d.get("pnl_usd"))
    fires[slug][tag] = (d.get("direction"), p)
    day = dt.datetime.utcfromtimestamp(fu / 1e6).strftime("%m-%d")
    daily[tag][day] += p

tags = list(SLEEVES.keys())
slugset = {t: {s for s, m in fires.items() if t in m} for t in tags}
print("fires per sleeve (window):", {t: len(slugset[t]) for t in tags})

print("\n=== SLUG OVERLAP (Jaccard %) — how much they trade the SAME markets ===")
print("%-22s" % "" + "".join("%-18s" % t for t in tags))
for a in tags:
    row = "%-22s" % a
    for b in tags:
        if a == b:
            row += "%-18s" % "—"
        else:
            inter = len(slugset[a] & slugset[b]); uni = len(slugset[a] | slugset[b])
            j = inter / uni * 100 if uni else 0
            row += "%-18s" % ("%.0f%% (%d common)" % (j, inter))
    print(row)

print("\n=== DIRECTION AGREEMENT on common slugs (%, of shared fires fire SAME side) ===")
print("%-22s" % "" + "".join("%-16s" % t for t in tags))
for a in tags:
    row = "%-22s" % a
    for b in tags:
        if a == b:
            row += "%-16s" % "—"; continue
        common = slugset[a] & slugset[b]
        if not common:
            row += "%-16s" % "n/a"; continue
        same = sum(1 for s in common if fires[s][a][0] == fires[s][b][0])
        row += "%-16s" % ("%.0f%% (n=%d)" % (same / len(common) * 100, len(common)))
    print(row)

# daily PnL correlation
alldays = sorted({d for t in tags for d in daily[t]})
def corr(x, y):
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((a - my) ** 2 for a in y))
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)

vec = {t: [daily[t].get(d, 0.0) for d in alldays] for t in tags}
print(f"\n=== DAILY-PnL CORRELATION (days={len(alldays)}: {alldays}) — low/neg = diversifies ===")
print("%-22s" % "" + "".join("%-10s" % t for t in tags))
for a in tags:
    row = "%-22s" % a
    for b in tags:
        row += "%-10s" % ("—" if a == b else "%+.2f" % corr(vec[a], vec[b]))
    print(row)
