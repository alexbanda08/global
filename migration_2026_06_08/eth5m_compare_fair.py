"""Fair ETH-5m sleeve comparison: scan ALL logs for each sleeve's true run-span, keep
only sleeves running >5 days AND active in the last 5 days, then measure EVERY sleeve on
the SAME most-recent-5-day window. v8 + V10 included."""
import json, glob
from collections import defaultdict

DAY = 86_400_000_000
rows = defaultdict(list)   # sleeve -> [(fire_us, pnl, won, vwap)]
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
        rows[d.get("sleeve_id", "?")].append((int(fu), float(p), bool(d.get("won")), d.get("fill_vwap")))

# global window = most recent 5 days
maxf = max(x[0] for v in rows.values() for x in v)
win_lo = maxf - 5 * DAY


def fmt(us):
    import datetime as dt
    return dt.datetime.utcfromtimestamp(us / 1e6).strftime("%m-%d")


def stats(v):
    v = sorted(v); pnl = [x[1] for x in v]; n = len(pnl)
    cum = peak = mdd = 0.0
    for p in pnl:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    tot = sum(pnl); wr = sum(1 for x in v if x[2]) / n
    vw = [x[3] for x in v if x[3] is not None]
    return n, wr, tot / n, tot, mdd, (tot / abs(mdd) if mdd < 0 else float("inf")), (sum(vw) / len(vw) if vw else 0)


qualified, excluded = [], []
for sid, v in rows.items():
    first, last = min(x[0] for x in v), max(x[0] for x in v)
    run_days = (last - first) / DAY
    active = last >= maxf - 1 * DAY            # fired in the last day
    runs_gt5 = first <= win_lo                 # started before the 5d window = >5 days
    win_v = [x for x in v if x[0] >= win_lo]   # restrict to common 5d window
    if runs_gt5 and active and len(win_v) >= 10:
        qualified.append((sid, stats(win_v), run_days, fmt(first), fmt(last)))
    else:
        excluded.append((sid, round(run_days, 1), len(win_v), active, runs_gt5))

print(f"common window: {fmt(win_lo)} -> {fmt(maxf)} (5 days)\n")
print(f"QUALIFIED (running >5d, active, >=10 fires in window) — {len(qualified)} sleeves, ranked $/tr:")
print("%-52s %4s %4s %7s %7s %6s %6s %5s %s" % ("sleeve", "n", "WR", "$/tr", "total", "MaxDD", "Calmr", "vwap", "runD"))
for sid, s, rd, fi, la in sorted(qualified, key=lambda r: -r[1][2]):
    n, wr, mean, tot, mdd, cal, vw = s
    mark = "  <== LIVE" if sid == "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10" else ("  <-- v8" if sid.endswith("grandparent_v8") else "")
    print("%-52s %4d %3.0f%% %+7.3f %+7.1f %6.1f %6.2f %5.3f %4.1f%s" % (sid[:52], n, wr*100, mean, tot, mdd, cal, vw, rd, mark))

print(f"\nEXCLUDED ({len(excluded)}): not >5d, or stopped, or <10 fires in window:")
for sid, rd, nw, act, gt5 in sorted(excluded, key=lambda r: -r[1]):
    why = []
    if not gt5: why.append("started_in_window")
    if not act: why.append("stopped")
    if nw < 10: why.append(f"only_{nw}_fires")
    print(f"  {sid[:54]:54s} run={rd}d  -> {','.join(why)}")
