# Round-8 session analysis: 28 new windows (Aug 21 18h / Aug 22 14h / Aug 23 03h / Aug 23 13h).
# Cash truth (buys/sells/redeems), winners from Chainlink resolutions, pairing,
# fill-timing, and GUARD COMPLIANCE (running max |up-dn| per window — post-fix
# sessions must stay <= ~5 sh + partial slack).
import json, csv, gzip
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
NEW = 1787320800
SESS = [("S1 Aug21 18h (broken guard)", 1787334000, 1787340000),
        ("S2 Aug22 14h", 1787400000, 1787410000),
        ("S3 Aug23 03h", 1787450000, 1787460000),
        ("S4 Aug23 13h", 1787488000, 1787495000)]

RES = {}
with open(DIR + r"\btc5m_resolutions_2wk.csv", newline="") as fh:
    for row in csv.DictReader(fh):
        RES[row["slug"]] = row["outcome"]

ts_l, cl_l = [], []
with gzip.open(DIR + r"\btc_1s_2wk.csv.gz", "rt", newline="") as fh:
    rd = csv.reader(fh); next(rd)
    for row in rd:
        ts_l.append(int(row[0]) // 1_000_000); cl_l.append(float(row[1]))
PX = dict(zip(ts_l, cl_l))
def px_at(t):
    for k in range(int(t), int(t) - 31, -1):
        if k in PX: return PX[k]
    return None

recs = json.load(open(DIR + r"\..\wallet_hunt\cache\_pm_portfolio\0x51a5f36d\activity_TRADE_2026_08_23a.json"))
reds = json.load(open(DIR + r"\..\wallet_hunt\cache\_pm_portfolio\0x51a5f36d\activity_REDEEM_2026_08_23a.json"))

W = defaultdict(lambda: dict(fills=[], sells=[], redeem=0.0, redeem_sh=0.0))
for r in recs:
    slug = r["slug"]
    if not slug.startswith("btc-updown-5m-") or int(slug.rsplit("-",1)[1]) < NEW: continue
    row = (r["timestamp"], r["outcome"] == "Up", float(r["price"]), float(r["size"]), float(r["usdcSize"]))
    (W[slug]["fills"] if r["side"] == "BUY" else W[slug]["sells"]).append(row)
for r in reds:
    slug = r.get("slug","")
    if slug in W or (slug.startswith("btc-updown-5m-") and int(slug.rsplit("-",1)[1]) >= NEW):
        W[slug]["redeem"] += float(r["usdcSize"]); W[slug]["redeem_sh"] += float(r["size"])

print(f"{'window':>28s} {'win':>4s} {'up/dn sh':>9s} {'maxImb':>6s} {'pair':>5s} {'buys':>7s} {'sells':>6s} {'redeem':>7s} {'net':>7s} {'fills>60s':>9s}")
tot = defaultdict(float)
sess_rows = defaultdict(list)
for slug in sorted(W, key=lambda s: int(s.rsplit("-",1)[1])):
    slot = int(slug.rsplit("-",1)[1])
    w = W[slug]
    w["fills"].sort(); w["sells"].sort()
    u = d = 0.0; maxi = 0.0; late = 0
    for (t, isup, px, sh, usd) in w["fills"]:
        if isup: u += sh
        else: d += sh
        maxi = max(maxi, abs(u - d))
        if t - slot > 60: late += 1
    buys = sum(x[4] for x in w["fills"]); sells = sum(x[4] for x in w["sells"])
    net = sells + w["redeem"] - buys
    win = RES.get(slug, "?")
    pair = min(u, d)
    sold_sh = sum(x[3] for x in w["sells"])
    print(f"{slug:>28s} {win[:4]:>4s} {u:4.0f}/{d:4.0f} {maxi:6.1f} {pair:5.0f} {buys:7.2f} {sells:6.2f} {w['redeem']:7.2f} {net:+7.2f} {late:9d}")
    for nm, lo, hi in SESS:
        if lo <= slot < hi:
            sess_rows[nm].append((slug, net, maxi, pair, u+d, buys))
print()
for nm, lo, hi in SESS:
    rows = sess_rows[nm]
    if not rows: continue
    net = sum(r[1] for r in rows); mx = max(r[2] for r in rows)
    pair = sum(r[3] for r in rows); tot_sh = sum(r[4] for r in rows)
    print(f"{nm:30s} n={len(rows):2d}  net {net:+7.2f}  worst maxImb {mx:5.1f} sh  paired {pair:5.0f}/{tot_sh:5.0f} sh  buys ${sum(r[5] for r in rows):.2f}")
# open positions check: windows with no redeem but residual on winner side => pending
print("\nunsettled/pending-redeem windows (redeem==0 but residual on winning side):")
for slug in sorted(W, key=lambda s: int(s.rsplit("-",1)[1])):
    w = W[slug]
    u = sum(x[3] for x in w["fills"] if x[1]) - sum(x[3] for x in w["sells"] if x[1])
    d = sum(x[3] for x in w["fills"] if not x[1]) - sum(x[3] for x in w["sells"] if not x[1])
    win = RES.get(slug)
    if w["redeem"] == 0 and win and ((win == "Up" and u > 0.01) or (win == "Down" and d > 0.01)):
        print(f"  {slug} win={win} residual up/dn {u:.1f}/{d:.1f} -> redemption MISSING (lag?)")
