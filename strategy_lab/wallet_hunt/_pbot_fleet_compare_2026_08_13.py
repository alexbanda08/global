"""PBot fleet comparison (2026-08-13): windows, overlap, side correlation.

For each bot: per-window net position sign (heavy side), timing fingerprint.
Cross-bot: window overlap matrix, same-window side agreement (phi), fill-second
proximity, per-window USD correlation. Common period = intersection of coverages.
"""
import json, math, os, re, sys
from collections import defaultdict, Counter

BOTS = {
    "PBot-2": "0x095fd7cc",
    "PBot-3": "0x74a2b82f",
    "PBot-5": "0x1b58d3de",
    "PBot-6": "0x21d0a97a",
}
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "_pm_portfolio")
SLUG = re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")

def load(short):
    p = f"{ROOT}/{short}/activity_TRADE_2026_08_13.json"
    return json.load(open(p)) if os.path.exists(p) else []

data = {}
for name, short in BOTS.items():
    tr = load(short)
    W = {}
    for t in tr:
        m = SLUG.match(t.get("slug") or "")
        if not m or t.get("side") != "BUY" or t.get("outcome") not in ("Up", "Down"):
            continue
        slot = int(m.group(3))
        w = W.setdefault(t["slug"], dict(tf=m.group(2), coin=m.group(1), slot=slot,
                                         sh={"Up": 0.0, "Down": 0.0}, usd=0.0,
                                         pre_usd=0.0, first=None, last=None))
        sz = float(t["size"]); us = float(t["usdcSize"]); off = t["timestamp"] - slot
        w["sh"][t["outcome"]] += sz; w["usd"] += us
        if off < 0: w["pre_usd"] += us
        w["first"] = off if w["first"] is None else min(w["first"], off)
        w["last"] = off if w["last"] is None else max(w["last"], off)
    ts = [t["timestamp"] for t in tr] or [0]
    data[name] = dict(W=W, t0=min(ts), t1=max(ts), n=len(tr))

# common period
t0 = max(d["t0"] for d in data.values())
t1 = min(d["t1"] for d in data.values())
import time as _t
print(f"common period: {_t.strftime('%Y-%m-%d %H:%M', _t.gmtime(t0))} .. {_t.strftime('%Y-%m-%d %H:%M', _t.gmtime(t1))} UTC "
      f"({(t1-t0)/86400:.1f} days)")

for name, d in data.items():
    Wc = {s: w for s, w in d["W"].items() if t0 <= w["slot"] <= t1}
    d["Wc"] = Wc
    if not Wc: continue
    pre = sum(w["pre_usd"] for w in Wc.values()); tot = sum(w["usd"] for w in Wc.values())
    ratio_p = sum(min(w["sh"]["Up"], w["sh"]["Down"]) for w in Wc.values())
    ratio_r = sum(abs(w["sh"]["Up"] - w["sh"]["Down"]) for w in Wc.values())
    tfs = Counter(w["tf"] for w in Wc.values())
    print(f"\n{name}: {d['n']} fills total | common-period windows {len(Wc)} ({dict(tfs)}) | "
          f"usd ${tot:,.0f} | pre-open {100*pre/max(tot,1e-9):.1f}% | paired:resid {ratio_p/max(ratio_r,1e-9):.2f}")

names = [n for n in BOTS if data[n]["Wc"]]
print("\n=== window overlap matrix (% of ROW's windows also traded by COL) ===")
print("         " + "  ".join(f"{n:>8}" for n in names))
for a in names:
    row = []
    for b in names:
        if a == b: row.append("     —"); continue
        inter = len(set(data[a]["Wc"]) & set(data[b]["Wc"]))
        row.append(f"{100*inter/max(len(data[a]['Wc']),1):5.1f}%")
    print(f"{a:>8} " + "  ".join(f"{x:>8}" for x in row))

def heavy(w):
    return 1 if w["sh"]["Up"] >= w["sh"]["Down"] else -1

print("\n=== side agreement on SHARED windows (heavy-side same?) + usd corr ===")
for i, a in enumerate(names):
    for b in names[i+1:]:
        shared = sorted(set(data[a]["Wc"]) & set(data[b]["Wc"]))
        if len(shared) < 30:
            print(f"{a} vs {b}: only {len(shared)} shared — skip"); continue
        sa = [heavy(data[a]["Wc"][s]) for s in shared]
        sb = [heavy(data[b]["Wc"][s]) for s in shared]
        agree = sum(1 for x, y in zip(sa, sb) if x == y) / len(shared)
        # phi
        n11 = sum(1 for x, y in zip(sa, sb) if x == 1 and y == 1)
        n10 = sum(1 for x, y in zip(sa, sb) if x == 1 and y == -1)
        n01 = sum(1 for x, y in zip(sa, sb) if x == -1 and y == 1)
        n00 = sum(1 for x, y in zip(sa, sb) if x == -1 and y == -1)
        den = math.sqrt(max((n11+n10)*(n01+n00)*(n11+n01)*(n10+n00), 1))
        phi = (n11*n00 - n10*n01) / den
        ua = [data[a]["Wc"][s]["usd"] for s in shared]
        ub = [data[b]["Wc"][s]["usd"] for s in shared]
        ma, mb = sum(ua)/len(ua), sum(ub)/len(ub)
        cov = sum((x-ma)*(y-mb) for x, y in zip(ua, ub))
        va = math.sqrt(sum((x-ma)**2 for x in ua)); vb = math.sqrt(sum((y-mb)**2 for y in ub))
        r = cov/max(va*vb, 1e-9)
        # first-fill offset delta
        fa = [data[a]["Wc"][s]["first"] for s in shared]
        fb = [data[b]["Wc"][s]["first"] for s in shared]
        import statistics as st
        dmed = st.median([x-y for x, y in zip(fa, fb)])
        print(f"{a} vs {b}: shared {len(shared)} | side-agree {100*agree:.1f}% (phi {phi:+.3f}) | "
              f"usd-corr {r:+.3f} | median Δfirst-fill {dmed:+.0f}s")

print("\n=== timing fingerprint (median first/last fill offset vs open, common period) ===")
import statistics as st
for n in names:
    Wc = data[n]["Wc"]
    fs = [w["first"] for w in Wc.values()]; ls = [w["last"] for w in Wc.values()]
    print(f"{n}: first fill median {st.median(fs):+.0f}s | last fill median {st.median(ls):+.0f}s")
