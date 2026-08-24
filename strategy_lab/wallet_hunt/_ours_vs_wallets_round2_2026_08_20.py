"""Round-2 same-window study (2026-08-20): OUR windows AFTER the Aug-18 cutoff
vs the reference wallets, canonical method from _ours_vs_wallets_2026_08_18.py.

NEW windows = slugs present in the _2026_08_20 fetch but absent from the
_2026_08_13 fetch of our wallet (that file was pulled Aug-18 14:27 and defines
the previous study's universe).
"""
import json, os, re, statistics as st, time
from collections import defaultdict

ROOT = "cache/_pm_portfolio"
SLUG = re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")
OURS = "0x51a5f36d"
REFS = {"b945": "0xb945945d", "b27": "0xb27bc932", "PBot-2": "0x095fd7cc",
        "PBot-3": "0x74a2b82f", "PBot-5": "0x1b58d3de", "PBot-6": "0x21d0a97a"}

def load(short, typ, tag):
    p = f"{ROOT}/{short}/activity_{typ}_{tag}.json"
    return json.load(open(p)) if os.path.exists(p) else []

def build(short, tag):
    red = defaultdict(float)
    for r in load(short, "REDEEM", tag):
        red[r.get("conditionId")] += float(r.get("usdcSize") or 0)
    red_sh = defaultdict(float)
    for r in load(short, "REDEEM", tag):
        red_sh[r.get("conditionId")] += float(r.get("size") or 0)
    W = {}
    for t in load(short, "TRADE", tag):
        m = SLUG.match(t.get("slug") or "")
        if not m or t.get("outcome") not in ("Up", "Down"):
            continue
        slot = int(m.group(3))
        w = W.setdefault(t["slug"], dict(coin=m.group(1), tf=m.group(2), slot=slot,
                                         cond=t.get("conditionId"),
                                         buy={"Up": [0.0, 0.0], "Down": [0.0, 0.0]},
                                         sell={"Up": [0.0, 0.0], "Down": [0.0, 0.0]},
                                         offs=defaultdict(list)))
        d = w["buy" if t["side"] == "BUY" else "sell"][t["outcome"]]
        d[0] += float(t["size"]); d[1] += float(t["usdcSize"])
        if t["side"] == "BUY":
            w["offs"][t["outcome"]].append(t["timestamp"] - slot)
    return W, red, red_sh

prev_slugs = set()
for t in load(OURS, "TRADE", "2026_08_13"):
    if SLUG.match(t.get("slug") or ""):
        prev_slugs.add(t["slug"])

ours, our_red, our_red_sh = build(OURS, "2026_08_20")
new = {s: w for s, w in ours.items() if s not in prev_slugs}
print(f"our windows in fresh fetch: {len(ours)} | NEW (post Aug-18 study): {len(new)}")
if not new:
    print("NO new windows — nothing to study."); raise SystemExit

refs = {}
for name, short in REFS.items():
    refs[name] = build(short, "2026_08_20")

def winner(slug, w):
    bu = w["buy"]["Up"][0] - w["sell"]["Up"][0]
    bd = w["buy"]["Down"][0] - w["sell"]["Down"][0]
    r = our_red_sh.get(w["cond"], 0)
    if r > 0.005:
        return "Up" if abs(r - bu) < abs(r - bd) else "Down"
    if bu < 1e-9 or bd < 1e-9:
        return "Down" if bu > 1e-9 else "Up"
    for RW, _, RRsh in refs.values():
        if slug in RW and RRsh.get(RW[slug]["cond"], 0) > 0.01:
            rw = RW[slug]
            hu = rw["buy"]["Up"][0] - rw["sell"]["Up"][0]
            hd = rw["buy"]["Down"][0] - rw["sell"]["Down"][0]
            return "Up" if abs(RRsh[rw["cond"]] - hu) < abs(RRsh[rw["cond"]] - hd) else "Down"
    return None

wins = {s: winner(s, w) for s, w in new.items()}
print(f"winners resolved: {sum(1 for v in wins.values() if v)}/{len(new)} "
      f"(unresolved: {[s for s, v in wins.items() if not v]})")

# ── sessions + cash identity ────────────────────────────────────────────────
def day(w): return time.strftime("%m-%d", time.gmtime(w["slot"]))
sess = defaultdict(list)
for s, w in new.items():
    sess[day(w)].append((s, w))
print("\n=== NEW sessions (cash) ===")
tot = 0.0
for d in sorted(sess):
    b = sum(w["buy"]["Up"][1] + w["buy"]["Down"][1] for _, w in sess[d])
    sl = sum(w["sell"]["Up"][1] + w["sell"]["Down"][1] for _, w in sess[d])
    r = sum(our_red.get(w["cond"], 0) for _, w in sess[d])
    bsh = sum(w["buy"]["Up"][0] + w["buy"]["Down"][0] for _, w in sess[d])
    tfs = defaultdict(int)
    for _, w in sess[d]: tfs[w["tf"]] += 1
    tot += sl + r - b
    print(f"{d}: {len(sess[d]):3d} w {dict(tfs)} | buys {bsh:7.1f} sh ${b:8.2f} | sells ${sl:7.2f} | "
          f"redeems ${r:8.2f} | net ${sl + r - b:+8.2f}")
print(f"NEW total net: ${tot:+.2f}")

# ── canonical legs: edge / timing / pairing ─────────────────────────────────
legs = []
for s, w in new.items():
    win = wins[s]
    for side in ("Up", "Down"):
        sh, usd = w["buy"][side]
        if sh > 1e-9 and win:
            legs.append(dict(off=st.median(w["offs"][side]) if w["offs"][side] else 0,
                             px=usd / sh, sh=sh, won=(side == win), tf=w["tf"], slug=s))
def blk(b, name):
    if not b: return
    S = sum(l["sh"] for l in b)
    wr = sum(l["sh"] * l["won"] for l in b) / S
    vw = sum(l["px"] * l["sh"] for l in b) / S
    print(f"  {name:>12}: {len(b):3d} legs {S:8.0f} sh  vwap {vw:.4f}  WR {100*wr:5.1f}%  "
          f"edge {(wr-vw)*100:+.2f}c/sh  (${(wr-vw)*S:+.1f})")
print("\n=== OUR edge (canonical) ===")
blk(legs, "ALL new")
for tf in ("5m", "15m"):
    blk([l for l in legs if l["tf"] == tf], tf)
print("timing buckets (median leg offset):")
for lo, hi, name in [(-1e9, 0, "pre-open"), (0, 60, "0-60s"), (60, 120, "60-120s"),
                     (120, 180, "120-180s"), (180, 1e9, ">180s")]:
    blk([l for l in legs if lo <= l["off"] < hi], name)

op = sum(min(w["buy"]["Up"][0], w["buy"]["Down"][0]) for w in new.values())
orr = sum(abs(w["buy"]["Up"][0] - w["buy"]["Down"][0]) for w in new.values())
print(f"pairing ratio (buys): {op/max(orr,1e-9):.2f}   (round-1 was 1.0-2.3 on shared)")

# ── wallets on OUR new windows ─────────────────────────────────────────────
print("\n=== wallets on OUR NEW windows ===")
for name, (RW, RRusd, RRsh) in refs.items():
    rlegs = []
    for s in new:
        if s not in RW or not wins[s]:
            continue
        for side in ("Up", "Down"):
            sh, usd = RW[s]["buy"][side]
            if sh > 1e-9:
                rlegs.append(dict(px=usd/sh, sh=sh, won=(side == wins[s]), off=0, tf="", slug=s))
    if len(rlegs) >= 4:
        blk(rlegs, name)
    else:
        print(f"  {name:>12}: present in {len(rlegs)} legs only — skip")

# price head-to-head same side/window
print("\nprice same-side same-window (our vwap − theirs, ¢/sh):")
for name, (RW, _, _) in refs.items():
    d = []
    for s in new:
        if s not in RW: continue
        for side in ("Up", "Down"):
            osh, ousd = new[s]["buy"][side]; tsh, tusd = RW[s]["buy"][side]
            if osh > 1e-9 and tsh > 1e-9:
                d.append((ousd/osh - tusd/tsh) * 100)
    if d:
        print(f"  {name}: {st.mean(d):+.2f}c mean / {st.median(d):+.2f}c median  (n={len(d)})")

# hold-vs-sell counterfactual
act = hold = 0.0
for s, w in new.items():
    win = wins[s]
    if not win: continue
    b = w["buy"]["Up"][1] + w["buy"]["Down"][1]
    sl = w["sell"]["Up"][1] + w["sell"]["Down"][1]
    act += sl + our_red.get(w["cond"], 0) - b
    hold += w["buy"][win][0] - b
print(f"\nhold-vs-sell: ACTUAL ${act:+.2f} | HOLD-ALL ${hold:+.2f} | selling effect ${act-hold:+.2f}")
