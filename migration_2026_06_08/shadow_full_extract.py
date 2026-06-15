"""Step 2 — FULL shadow window per candidate sleeve (all available days, May27->Jun9).
Per-fire dump to CSV for local ml4t DSR + bootstrap. No 5-day slicing."""
import json, glob, csv

SL = {
    "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8": "v8_grandparent",
    "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10": "v10_grandparent",
    "poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7": "v6c3_v7",
    "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10": "cloud_ribbon_V10",
    "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6": "cloud_ribbon_v6",
    "poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7": "cloud_vwap_v7",
}
out = []
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-*.jsonl")):
    for line in open(f):
        if "sleeve_fire_resolved" not in line:
            continue
        if not any(s in line for s in SL):
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        sid = d.get("sleeve_id")
        if sid not in SL or d.get("event_type") != "sleeve_fire_resolved":
            continue
        p = d.get("pnl_usd")
        if p is None:
            continue
        out.append([SL[sid], d.get("fire_us"), float(p), 1 if d.get("won") else 0,
                    d.get("fill_vwap"), d.get("slug")])

with open("/tmp/shadow_full.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["tag", "fire_us", "pnl", "won", "vwap", "slug"])
    w.writerows(out)
print("rows:", len(out))
from collections import Counter
print(Counter(r[0] for r in out))
