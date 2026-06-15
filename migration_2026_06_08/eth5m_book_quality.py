"""Per-sleeve book quality on PLACED fires (fair 5d window) — confirm the winners aren't
winning via systematically wider/thinner books than v8. Same shadow fill rules for all."""
import json, glob
from collections import defaultdict

DAY = 86_400_000_000
TARGET = {
    "poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7",
    "poly_sniper_v5_eth_5m_tr200_mp_sms_active_off120",
    "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10",
    "poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7",
    "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6",
    "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10",
    "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8",
}
agg = defaultdict(lambda: {"n": 0, "cross": [], "bidask": [], "ws": 0, "depth": []})
maxf = 0
recs = []
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-06-0[4-9].jsonl")):
    for line in open(f):
        if "sleeve_fire_placed" not in line:
            continue
        ok = False
        for t in TARGET:
            if t in line:
                ok = True; break
        if not ok:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("sleeve_id") not in TARGET or d.get("event_type") != "sleeve_fire_placed":
            continue
        recs.append(d); maxf = max(maxf, d.get("fire_us", 0))
win_lo = maxf - 5 * DAY
for d in recs:
    if d.get("fire_us", 0) < win_lo:
        continue
    a = agg[d["sleeve_id"]]
    a["n"] += 1
    snap = d.get("l25_book_snapshot") or {}
    cs = snap.get("cross_spread_old") or snap.get("cross_spread")
    if cs is not None:
        a["cross"].append(float(cs))
    dr = d.get("direction")
    ask = snap.get("up_ask0" if dr == "UP" else "dn_ask0")
    bid = snap.get("up_bid0" if dr == "UP" else "dn_bid0")
    if ask is not None and bid is not None:
        a["bidask"].append(float(ask) - float(bid))
    dep = snap.get("up_depth_usd" if dr == "UP" else "dn_depth_usd")
    if dep is not None:
        a["depth"].append(float(dep))
    if (snap.get("up_book_source") == "ws_mirror"):
        a["ws"] += 1


def med(x):
    if not x:
        return float("nan")
    x = sorted(x); return x[len(x) // 2]


print("per-sleeve PLACED book quality (fair 5d window):")
print("%-50s %4s %9s %9s %9s %6s" % ("sleeve", "n", "med_cross", "med_bidask", "med_depth$", "%ws"))
for sid, a in sorted(agg.items(), key=lambda kv: med(kv[1]["cross"])):
    n = a["n"]
    print("%-50s %4d %9.3f %9.3f %9.0f %5.0f%%" %
          (sid[:50], n, med(a["cross"]), med(a["bidask"]), med(a["depth"]), 100 * a["ws"] / n if n else 0))
