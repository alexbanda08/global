"""OUR live windows vs the reference wallets, same-window join (2026-08-18).

Part 1: reconstruct OUR live per-window book from data-api (buys+sells+redeems),
        validate against the hand-reconciled Aug-13 number (net -8.54).
Part 2: same-slug join vs b945 / b27 / PBot-2/3/5/6 caches.
Part 3: counterfactual sims (price-swap, hold-vs-sell).
"""
import json, os, re, statistics as st, sys, time
from collections import defaultdict

ROOT = "cache/_pm_portfolio"
SLUG = re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")
OURS = "0x51a5f36d"
REFS = {"b945": "0xb945945d", "b27": "0xb27bc932", "PBot-2": "0x095fd7cc",
        "PBot-3": "0x74a2b82f", "PBot-5": "0x1b58d3de", "PBot-6": "0x21d0a97a"}

def load(short, typ):
    p = f"{ROOT}/{short}/activity_{typ}_2026_08_13.json"
    return json.load(open(p)) if os.path.exists(p) else []

def build(short, with_sells=False):
    """slug -> per-side buy/sell (sh,usd,offsets), redeem via conditionId."""
    trades = load(short, "TRADE")
    red = defaultdict(float)
    for r in load(short, "REDEEM"):
        red[r.get("conditionId")] += float(r.get("usdcSize") or 0)
    W = {}
    for t in trades:
        m = SLUG.match(t.get("slug") or "")
        if not m or t.get("outcome") not in ("Up", "Down"):
            continue
        slot = int(m.group(3))
        w = W.setdefault(t["slug"], dict(coin=m.group(1), tf=m.group(2), slot=slot,
                                         cond=t.get("conditionId"),
                                         buy={"Up": [0.0, 0.0], "Down": [0.0, 0.0]},
                                         sell={"Up": [0.0, 0.0], "Down": [0.0, 0.0]},
                                         offs=[]))
        d = w["buy" if t["side"] == "BUY" else "sell"][t["outcome"]]
        d[0] += float(t["size"]); d[1] += float(t["usdcSize"])
        if t["side"] == "BUY":
            w["offs"].append(t["timestamp"] - slot)
    for w in W.values():
        w["red_usd"] = red.get(w["cond"], 0.0)
    return W

ours = build(OURS, with_sells=True)
print(f"OUR windows: {len(ours)}")

# ── Part 1: session table + validation ─────────────────────────────────────
def day_of(slot): return time.strftime("%m-%d", time.gmtime(slot))
sessions = defaultdict(list)
for slug, w in ours.items():
    sessions[day_of(w["slot"])].append(w)

print("\n=== OUR sessions (cash: sells + redeems − buys) ===")
tot = dict(b=0.0, s=0.0, r=0.0)
for d in sorted(sessions):
    ws = sessions[d]
    b = sum(w["buy"]["Up"][1] + w["buy"]["Down"][1] for w in ws)
    s = sum(w["sell"]["Up"][1] + w["sell"]["Down"][1] for w in ws)
    r = sum(w["red_usd"] for w in ws)
    bsh = sum(w["buy"]["Up"][0] + w["buy"]["Down"][0] for w in ws)
    ssh = sum(w["sell"]["Up"][0] + w["sell"]["Down"][0] for w in ws)
    tot["b"] += b; tot["s"] += s; tot["r"] += r
    print(f"{d}: {len(ws):3d} windows | buys {bsh:7.1f} sh ${b:8.2f} | sells {ssh:6.1f} sh ${s:7.2f} | "
          f"redeems ${r:8.2f} | net ${s + r - b:+8.2f}")
print(f"ALL: buys ${tot['b']:.2f} sells ${tot['s']:.2f} redeems ${tot['r']:.2f} net ${tot['s']+tot['r']-tot['b']:+.2f}")
print("VALIDATION Aug-13 handoff says: buys $207.50, sells $73.17, redeems $125.79, net -$8.54")

# ── Part 2: same-window join ───────────────────────────────────────────────
refs = {name: build(short) for name, short in REFS.items()}
print("\n=== same-window presence ===")
for name, R in refs.items():
    shared = [s for s in ours if s in R]
    print(f"{name}: shares {len(shared)} of our {len(ours)} windows")

# detailed comparison on shared windows: price + timing + pairing
print("\n=== head-to-head on shared windows (per wallet) ===")
for name, R in refs.items():
    shared = [s for s in ours if s in R]
    if len(shared) < 5:
        continue
    dpx = []   # our buy vwap − their buy vwap, same side, same window (side-weighted)
    for s in shared:
        for side in ("Up", "Down"):
            osh, ousd = ours[s]["buy"][side]
            tsh, tusd = R[s]["buy"][side]
            if osh > 1e-9 and tsh > 1e-9:
                dpx.append((ousd / osh) - (tusd / tsh))
    o_off = [o for s in shared for o in ours[s]["offs"]]
    t_off = [o for s in shared for o in R[s]["offs"]]
    op = sum(min(ours[s]["buy"]["Up"][0], ours[s]["buy"]["Down"][0]) for s in shared)
    orr = sum(abs(ours[s]["buy"]["Up"][0] - ours[s]["buy"]["Down"][0]) for s in shared)
    tp = sum(min(R[s]["buy"]["Up"][0], R[s]["buy"]["Down"][0]) for s in shared)
    tr = sum(abs(R[s]["buy"]["Up"][0] - R[s]["buy"]["Down"][0]) for s in shared)
    print(f"\n{name} ({len(shared)} shared windows, {len(dpx)} same-side legs):")
    if dpx:
        print(f"  price: WE pay {st.mean(dpx)*100:+.2f}c/share vs them (median {st.median(dpx)*100:+.2f}c)")
    if o_off and t_off:
        print(f"  timing: our median buy offset {st.median(o_off):+.0f}s vs theirs {st.median(t_off):+.0f}s")
    print(f"  pairing: ours {op/max(orr,1e-9):.2f} vs theirs {tp/max(tr,1e-9):.2f}")

# ── Part 3: counterfactual sims ────────────────────────────────────────────
# winner per window: prefer our redeem inference; fall back to any ref wallet's
def winner(slug):
    w = ours[slug]
    bu, bd = w["buy"]["Up"][0] - w["sell"]["Up"][0], w["buy"]["Down"][0] - w["sell"]["Down"][0]
    if w["red_usd"] > 0.005:
        # redeemed shares = winning-side held-at-settle shares
        return "Up" if abs(w["red_usd"] - bu) < abs(w["red_usd"] - bd) else "Down"
    for R in refs.values():
        if slug in R and R[slug]["red_usd"] > 0.005:
            rw = R[slug]
            rbu, rbd = rw["buy"]["Up"][0] - rw["sell"]["Up"][0], rw["buy"]["Down"][0] - rw["sell"]["Down"][0]
            return "Up" if abs(rw["red_usd"] - rbu) < abs(rw["red_usd"] - rbd) else "Down"
    return None

known = {s: winner(s) for s in ours}
nk = sum(1 for v in known.values() if v)
print(f"\nwinner known for {nk}/{len(ours)} windows")

# S2: hold-vs-sell counterfactual: our actual = sells+red-buys; hold-all = settle value of ALL buys − buys
act = hold = 0.0; nscored = 0
for s, w in ours.items():
    win = known[s]
    if not win:
        continue
    b = w["buy"]["Up"][1] + w["buy"]["Down"][1]
    sell = w["sell"]["Up"][1] + w["sell"]["Down"][1]
    act += sell + w["red_usd"] - b
    hold += w["buy"][win][0] * 1.0 - b
    nscored += 1
print(f"\nS2 hold-vs-sell ({nscored} windows): ACTUAL net ${act:+.2f} | HOLD-ALL net ${hold:+.2f} | selling added ${act-hold:+.2f}")

# S1: price-swap: our shares at the ref wallet's same-side same-window vwap (b945 first, else PBot-6)
swap_gain = 0.0; legs = 0
for s, w in ours.items():
    for side in ("Up", "Down"):
        osh, ousd = w["buy"][side]
        if osh <= 1e-9:
            continue
        for name in ("b945", "PBot-6", "PBot-2"):
            R = refs[name]
            if s in R and R[s]["buy"][side][0] > 1e-9:
                tv = R[s]["buy"][side][1] / R[s]["buy"][side][0]
                swap_gain += ousd - tv * osh   # what we'd save at their price
                legs += 1
                break
print(f"S1 price-swap ({legs} legs benchmarked): buying at the wallets' same-window price would have saved ${swap_gain:+.2f}")
