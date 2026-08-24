"""How does PBot-6 end up holding the winning side 51.6% of the time? (2026-08-13)

Hypotheses:
  H-A discount-only: rests bids on BOTH tokens below 0.50 pre-open; the filled side is
      chosen by SELLER FLOW, WR ~ base rate; profit = discount.
  H-B drift: WR>50% just because Up (or Down) won >50% in the period and its book skews.
  H-C momentum/contrarian: side correlates with previous window's winner.
  H-D price-skill: WR exceeds entry-price-implied breakeven uniformly (real selection).
"""
import json, re, statistics as st, sys
from collections import defaultdict, Counter

SHORT = "0x21d0a97a"
ROOT = f"cache/_pm_portfolio/{SHORT}"
SLUG = re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")

trades = json.load(open(f"{ROOT}/activity_TRADE_2026_08_13.json"))
redeems = json.load(open(f"{ROOT}/activity_REDEEM_2026_08_13.json"))
red = defaultdict(float)
for r in redeems:
    red[r.get("conditionId")] += float(r.get("size") or 0)
max_red = max(r["timestamp"] for r in redeems)

W = {}
for t in trades:
    m = SLUG.match(t.get("slug") or "")
    if not m or t.get("side") != "BUY" or t.get("outcome") not in ("Up", "Down"):
        continue
    slot = int(m.group(3))
    w = W.setdefault(t["slug"], dict(coin=m.group(1), tf=m.group(2), slot=slot,
                                     cond=t.get("conditionId"),
                                     sh={"Up": 0.0, "Down": 0.0}, usd={"Up": 0.0, "Down": 0.0},
                                     pre_sh={"Up": 0.0, "Down": 0.0}))
    sz, us = float(t["size"]), float(t["usdcSize"])
    w["sh"][t["outcome"]] += sz
    w["usd"][t["outcome"]] += us
    if t["timestamp"] < slot:
        w["pre_sh"][t["outcome"]] += sz

rows = []
for slug, w in W.items():
    wl = 300 if w["tf"] == "5m" else 900
    if w["slot"] + wl > max_red - 3600:
        continue
    bu, bd = w["sh"]["Up"], w["sh"]["Down"]
    if bu + bd <= 0:
        continue
    rs = red.get(w["cond"], 0.0)
    # winner: redemption == winning-side holdings (never sells)
    if rs > 0.01:
        winner = "Up" if abs(rs - bu) < abs(rs - bd) else "Down"
    else:
        if bu > 0 and bd > 0:   # held both, redeemed none -> ambiguous, skip
            continue
        winner = "Down" if bu > 0 else "Up"   # held one side, it expired
    heavy = "Up" if bu >= bd else "Down"
    vw = w["usd"][heavy] / w["sh"][heavy]
    rows.append(dict(coin=w["coin"], tf=w["tf"], slot=w["slot"], heavy=heavy,
                     winner=winner, vw=vw, won=heavy == winner,
                     pre_both=(w["pre_sh"]["Up"] > 0 and w["pre_sh"]["Down"] > 0),
                     pre_any=(w["pre_sh"]["Up"] + w["pre_sh"]["Down"] > 0),
                     one_sided=(bu == 0 or bd == 0)))

print(f"windows scored: {len(rows)}")

n = len(rows)
wr = sum(r["won"] for r in rows) / n
up_heavy = sum(1 for r in rows if r["heavy"] == "Up") / n
up_won = sum(1 for r in rows if r["winner"] == "Up") / n
print(f"\nH-B drift check:")
print(f"  heavy-side WR: {100*wr:.2f}%  | P(heavy=Up): {100*up_heavy:.2f}%  | base P(Up wins): {100*up_won:.2f}%")
wr_up = [r["won"] for r in rows if r["heavy"] == "Up"]
wr_dn = [r["won"] for r in rows if r["heavy"] == "Down"]
print(f"  WR when heavy=Up: {100*st.mean(wr_up):.2f}% (n={len(wr_up)}) | heavy=Down: {100*st.mean(wr_dn):.2f}% (n={len(wr_dn)})")

print(f"\nH-A both-sides-resting check (pre-open windows only):")
pre = [r for r in rows if r["pre_any"]]
print(f"  windows with pre-open fills: {len(pre)} | of those, BOTH sides pre-filled: {100*st.mean([r['pre_both'] for r in pre]):.1f}%")
print(f"  one-sided windows overall: {100*st.mean([r['one_sided'] for r in rows]):.1f}%")

print(f"\nH-D calibration: WR vs entry price (breakeven = price)")
for lo, hi in [(0.30, 0.42), (0.42, 0.46), (0.46, 0.48), (0.48, 0.50), (0.50, 0.52), (0.52, 0.60)]:
    b = [r for r in rows if lo <= r["vw"] < hi]
    if len(b) < 100:
        continue
    w_ = st.mean([r["won"] for r in b])
    px = st.mean([r["vw"] for r in b])
    se = (w_ * (1 - w_) / len(b)) ** 0.5
    print(f"  px {lo:.2f}-{hi:.2f}: n={len(b):5d}  avg px {px:.4f}  WR {100*w_:.2f}%  excess vs px {100*(w_-px):+.2f}pp  (z={ (w_-px)/se:+.1f})")

print(f"\nH-C momentum: buy side vs PREVIOUS window winner (same coin+tf chain)")
by_key = {(r["coin"], r["tf"], r["slot"]): r for r in rows}
mom = []
for r in rows:
    step = 300 if r["tf"] == "5m" else 900
    prev = by_key.get((r["coin"], r["tf"], r["slot"] - step))
    if prev:
        mom.append((r["heavy"] == prev["winner"], r["won"]))
if mom:
    follow = st.mean([m[0] for m in mom])
    wr_follow = st.mean([m[1] for m in mom if m[0]]) if any(m[0] for m in mom) else 0
    wr_fade = st.mean([m[1] for m in mom if not m[0]]) if any(not m[0] for m in mom) else 0
    print(f"  n={len(mom)} | P(heavy == prev winner): {100*follow:.2f}%  "
          f"| WR when following: {100*wr_follow:.2f}%  | WR when fading: {100*wr_fade:.2f}%")

print(f"\nsplit by tf/coin (heavy WR):")
for tf in ("5m", "15m"):
    for coin in ("btc", "eth"):
        b = [r for r in rows if r["tf"] == tf and r["coin"] == coin]
        if len(b) < 100: continue
        print(f"  {coin}-{tf}: n={len(b)}  WR {100*st.mean([r['won'] for r in b]):.2f}%  avg px {st.mean([r['vw'] for r in b]):.4f}  P(Up wins) {100*st.mean([r['winner']=='Up' for r in b]):.2f}%")
