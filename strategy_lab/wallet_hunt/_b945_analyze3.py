"""b945: price-band x window-offset structure + sweeper + maker evidence.

Cross-validates the operator's article claims against his actual tape:
 - EV layering -> buys across whole price curve (band distribution)
 - lag entries -> early/mid-window cheap-leg buys
 - drawdown hedging -> later opposite-side buys
 - sweeper -> end-of-window >=0.97 buys
 - maker vs taker -> MAKER_REBATE totals
"""
import json, re, collections, datetime as dt

P = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/"
tr = json.load(open(P + "activity_TRADE.json"))
reb = json.load(open(P + "activity_MAKER_REBATE.json"))

# slug suffix = slot_start (s). 15m window = 900s.
rx = re.compile(r"^btc-updown-15m-(\d+)$")
rows = []
for t in tr:
    m = rx.match(t.get("slug") or "")
    if not m or t["side"] != "BUY":
        continue
    off = t["timestamp"] - int(m.group(1))
    rows.append((t["price"], off, t["usdcSize"], t["size"], t["outcome"], t["conditionId"]))

print("n BUY fills on btc-15m:", len(rows))

# offset can be negative (pre-open) or >900 (post-window pre-resolution lag)
bands = [(0, .10), (.10, .30), (.30, .55), (.55, .80), (.80, .97), (.97, 1.01)]
print("\nprice band | n | usd | offset p10/p50/p90 (s of 900)")
for lo, hi in bands:
    sub = [r for r in rows if lo <= r[0] < hi]
    if not sub:
        print(f"{lo:.2f}-{hi:.2f} | 0"); continue
    offs = sorted(r[1] for r in sub)
    usd = sum(r[2] for r in sub)
    def pc(p): return offs[int(p * (len(offs) - 1))]
    print(f"{lo:.2f}-{hi:.2f} | {len(sub):4d} | ${usd:8.0f} | {pc(.1):4d} / {pc(.5):4d} / {pc(.9):4d}")

# sweeper check: >=0.97 buys near window end
sw = [r for r in rows if r[0] >= 0.97]
print("\nsweeper candidates (price>=0.97): n=%d usd=$%.0f" % (len(sw), sum(r[2] for r in sw)))
if sw:
    offs = sorted(r[1] for r in sw)
    print("  offsets p10/p50/p90: %d / %d / %d" % (
        offs[int(.1 * (len(offs) - 1))], offs[len(offs) // 2], offs[int(.9 * (len(offs) - 1))]))

# tail check: <=0.10 buys (asymmetric cheap tail)
tl = [r for r in rows if r[0] <= 0.10]
print("cheap tail (price<=0.10): n=%d usd=$%.0f" % (len(tl), sum(r[2] for r in tl)))

# per-market sequencing: which side first, does opposite side follow after adverse move?
seq_first_cheap = 0; seq_n = 0
by_mkt = collections.defaultdict(list)
for t in tr:
    m = rx.match(t.get("slug") or "")
    if not m or t["side"] != "BUY":
        continue
    by_mkt[t["conditionId"]].append((t["timestamp"], t["outcome"], t["price"]))
n_alternations = []
for c, fills in by_mkt.items():
    fills.sort()
    sides = [f[1] for f in fills]
    alt = sum(1 for i in range(1, len(sides)) if sides[i] != sides[i - 1])
    n_alternations.append((alt, len(sides)))
alts = sorted(a / max(b - 1, 1) for a, b in n_alternations if b > 5)
if alts:
    print("\nside-alternation rate per market (frac of consecutive fills switching side):")
    print("  p10 %.2f p50 %.2f p90 %.2f  (0=blocks per side, 1=ping-pong)" % (
        alts[int(.1 * (len(alts) - 1))], alts[len(alts) // 2], alts[int(.9 * (len(alts) - 1))]))

# maker rebates
rtot = sum(r.get("usdcSize", 0) for r in reb)
print("\nMAKER_REBATE events: %d, total $%.2f" % (len(reb), rtot))
if reb:
    rts = [r["timestamp"] for r in reb]
    print("  rebate window:", dt.datetime.utcfromtimestamp(min(rts)), "->",
          dt.datetime.utcfromtimestamp(max(rts)))
