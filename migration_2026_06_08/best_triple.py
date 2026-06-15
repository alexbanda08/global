"""Best 3-sleeve portfolio: merge per-fire PnL streams (time-ordered), compute combined
total / MaxDD / Calmar / daily-Sharpe for every triple. Diversification => lower combined DD."""
import json, glob, math, itertools
from collections import defaultdict
import datetime as dt

DAY = 86_400_000_000
POOL = {
    "v6c3_v7": "poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7",
    "ribbon_V10": "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10",
    "vwap_v7": "poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7",
    "ribbon_v6": "poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6",
    "tr200_off120": "poly_sniper_v5_eth_5m_tr200_mp_sms_active_off120",
    "hlcascade50k": "poly_sniper_v5_eth_5m_a2_hlcascade50k_v9",
}
ID2 = {v: k for k, v in POOL.items()}
recs = []
maxf = 0
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-06-0[4-9].jsonl")):
    for line in open(f):
        if "sleeve_fire_resolved" not in line:
            continue
        if not any(s in line for s in POOL.values()):
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("sleeve_id") not in ID2 or d.get("event_type") != "sleeve_fire_resolved":
            continue
        recs.append(d); maxf = max(maxf, d.get("fire_us", 0))
win_lo = maxf - 5 * DAY
# tag -> list of (fire_us, pnl)
streams = defaultdict(list)
for d in recs:
    fu = d.get("fire_us", 0)
    if fu < win_lo:
        continue
    streams[ID2[d["sleeve_id"]]].append((fu, float(d["pnl_usd"])))


def port_metrics(fires):
    fires = sorted(fires)
    pnl = [p for _, p in fires]
    n = len(pnl)
    cum = peak = mdd = 0.0
    for p in pnl:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    tot = sum(pnl)
    daily = defaultdict(float)
    for fu, p in fires:
        daily[dt.datetime.utcfromtimestamp(fu / 1e6).strftime("%m-%d")] += p
    dv = list(daily.values())
    sh = (sum(dv) / len(dv)) / (math.sqrt(sum((x - sum(dv) / len(dv)) ** 2 for x in dv) / len(dv)) or 1e9) * math.sqrt(365) if len(dv) > 1 else 0
    cal = tot / abs(mdd) if mdd < 0 else float("inf")
    return n, tot, mdd, cal, sh


print("singles:")
for t in POOL:
    n, tot, mdd, cal, sh = port_metrics(streams[t])
    print("  %-14s n=%4d tot=%+7.1f MaxDD=%6.1f Calmar=%5.2f Sharpe=%5.2f" % (t, n, tot, mdd, cal, sh))

print("\nALL TRIPLES (ranked by combined Calmar):")
res = []
for combo in itertools.combinations(POOL, 3):
    allf = []
    for t in combo:
        allf += streams[t]
    n, tot, mdd, cal, sh = port_metrics(allf)
    res.append((combo, n, tot, mdd, cal, sh))
for combo, n, tot, mdd, cal, sh in sorted(res, key=lambda r: -r[4]):
    print("  %-38s n=%4d tot=%+7.1f $/tr=%+.3f MaxDD=%6.1f Calmar=%5.2f Sharpe=%5.2f"
          % ("+".join(combo), n, tot, tot / n, mdd, cal, sh))
