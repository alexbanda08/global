"""Aggregate ALL ETH 5m shadow sleeves on VPS3 (sleeve_fire_resolved), same window,
rank vs eth_5m_l_ema50_hurst_grandparent_v8/V10 (the live sleeve family)."""
import json, glob, math
from collections import defaultdict

rows = defaultdict(list)  # sleeve -> list of (fire_us, pnl, won, vwap)
firsts, lasts = {}, {}
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-06-0[4-9].jsonl")):
    day = f.split("/")[-1][:10]
    for line in open(f):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("event_type") != "sleeve_fire_resolved":
            continue
        if d.get("asset") != "ETH" or d.get("tf") != "5m":
            continue
        p = d.get("pnl_usd")
        if p is None:
            continue
        sid = d.get("sleeve_id", "?")
        rows[sid].append((d.get("fire_us", 0), float(p), bool(d.get("won")),
                          d.get("fill_vwap")))
        firsts.setdefault(sid, day); lasts[sid] = day


def stats(v):
    v = sorted(v)
    pnl = [x[1] for x in v]
    n = len(pnl)
    cum, peak, mdd, c = 0.0, 0.0, 0.0, 0.0
    for p in pnl:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    wr = sum(1 for x in v if x[2]) / n
    tot = sum(pnl); mean = tot / n
    calmar = tot / abs(mdd) if mdd < 0 else float("inf")
    vw = [x[3] for x in v if x[3] is not None]
    avgvw = sum(vw) / len(vw) if vw else float("nan")
    return n, wr, mean, tot, mdd, calmar, avgvw


out = []
for sid, v in rows.items():
    n, wr, mean, tot, mdd, calmar, avgvw = stats(v)
    out.append((sid, n, wr, mean, tot, mdd, calmar, avgvw, firsts[sid] + ".." + lasts[sid]))

# rank by mean $/tr, require n>=20 for signal
print("ALL ETH-5m shadow sleeves (VPS3, Jun4-9), ranked by $/tr  [* = n>=20]")
print("%-52s %5s %5s %7s %8s %7s %7s %6s  span" % ("sleeve", "n", "WR", "$/tr", "total", "MaxDD", "Calmar", "vwap"))
for r in sorted(out, key=lambda r: -r[3]):
    sid, n, wr, mean, tot, mdd, calmar, avgvw, span = r
    star = "*" if n >= 20 else " "
    print("%-52s %5d %4.0f%% %+7.3f %+8.1f %7.1f %7.2f %6.3f%s %s" %
          (sid[:52], n, wr * 100, mean, tot, mdd, calmar, avgvw, star, span))
print(f"\nTOTAL sleeves: {len(out)}")
# highlight the grandparent family
print("\n--- grandparent family (the live one) ---")
for r in sorted(out, key=lambda r: -r[3]):
    if "grandparent" in r[0]:
        print("  %-50s n=%d WR=%.0f%% $/tr=%+.3f Calmar=%.2f" % (r[0], r[1], r[2]*100, r[3], r[6]))
