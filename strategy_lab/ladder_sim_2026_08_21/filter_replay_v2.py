# AUDITED v2 of filter_replay: fixes the F2 time-ordering defect (v1 ran the exit
# scan over the FINAL book, so it could sell at el=E shares that were only bought
# later = lookahead). v2 merges buy fills and exit-check ticks chronologically and
# sells only what is actually held at the trigger moment.
# Everything else identical to v1 so the diff isolates the bug's impact.
import json, gzip, csv
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
CLIP = 5.0

ts_l, cl_l = [], []
with gzip.open(DIR + r"\btc_1s_2wk.csv.gz", "rt", newline="") as fh:
    rd = csv.reader(fh); next(rd)
    for row in rd:
        ts_l.append(int(row[0]) // 1_000_000); cl_l.append(float(row[1]))
PX = dict(zip(ts_l, cl_l)); PLO = ts_l[0]
def px_at(t):
    for k in range(int(t), max(PLO, int(t) - 30) - 1, -1):
        v = PX.get(k)
        if v is not None:
            return v
    return None

RES = {}
with open(DIR + r"\btc5m_resolutions_2wk.csv", newline="") as fh:
    for row in csv.DictReader(fh):
        RES[row["slug"]] = row["outcome"]
def winner_up(slug, start):
    o = RES.get(slug)
    if o:
        return o == "Up", False
    b0, b1 = px_at(start), px_at(start + 299)
    return (b1 or 0) > (b0 or 0), True

recs = json.load(open(DIR + r"\..\wallet_hunt\cache\_pm_portfolio\0x51a5f36d\activity_TRADE_2026_08_21c.json"))
buys = defaultdict(list)
for r in recs:
    if r["side"] == "BUY" and r["slug"].startswith("btc-updown-5m-"):
        buys[r["slug"]].append((r["timestamp"], r["outcome"] == "Up",
                                float(r["price"]), float(r["size"])))
for v in buys.values():
    v.sort()

need = set(buys)
prints = defaultdict(list)
with gzip.open(DIR + r"\btc5m_trades_2wk.csv.gz", "rt", newline="") as fh:
    rd = csv.reader(fh); h = next(rd); ix = {c: i for i, c in enumerate(h)}
    for row in rd:
        if row[ix["slug"]] in need:
            prints[row[ix["slug"]]].append((int(row[ix["timestamp_us"]]) / 1e6,
                                            row[ix["outcome"]][0] == "U",
                                            float(row[ix["price"]])))
for v in prints.values():
    v.sort()

def last_print(slug, is_up, t):
    best = None
    for (pt, u, p) in prints.get(slug, []):
        if pt > t:
            break
        if u == is_up:
            best = p
    return best

def run(policy, D=None, E=None, haircut=0.01):
    tot = 0.0; blocked_sh = 0.0; exits = 0; fallback = 0
    per = []
    for slug, seq in buys.items():
        start = int(slug.rsplit("-", 1)[1])
        wu, fb = winner_up(slug, start)
        fallback += fb
        b0 = px_at(start)
        # chronological event stream: (t, kind, payload); exit checks every 5s
        events = [(t, 0, (is_up, prc, sh)) for (t, is_up, prc, sh) in seq]
        if policy == "g1f1b_x" and E is not None:
            events += [(start + el, 1, None) for el in range(E, 296, 5)]
        events.sort(key=lambda e: (e[0], e[1]))
        u = d_ = uc = dc = 0.0
        exit_pnl = 0.0; exited = False
        for (t, kind, pl) in events:
            if kind == 0:
                is_up, prc, sh = pl
                b = px_at(t)
                disp = (b - b0) if (b0 and b) else 0.0
                leader_up = disp > 0
                s_sh, o_sh = (u, d_) if is_up else (d_, u)
                block = False
                if policy in ("g1", "g1f1b", "g1f1b_x") and (s_sh - o_sh) >= CLIP - 1e-9:
                    block = True
                if not block and D is not None and policy in ("f1a", "f1b", "g1f1b", "g1f1b_x"):
                    is_loser = (is_up != leader_up) and abs(disp) >= D
                    if is_loser and (policy == "f1a" or s_sh >= o_sh - 1e-9):
                        block = True
                if block:
                    blocked_sh += sh
                    continue
                if is_up: u += sh; uc += sh * prc
                else:     d_ += sh; dc += sh * prc
            else:
                if exited:
                    continue
                b = px_at(t)
                if not (b0 and b):
                    continue
                disp = b - b0
                net_up = u - d_
                if abs(disp) < D or abs(net_up) < 1e-9:
                    continue
                heavy_up = net_up > 0
                if heavy_up == (disp > 0):
                    continue
                lp = last_print(slug, heavy_up, t)
                if lp is None:
                    continue
                px_sell = max(lp - haircut, 0.01)
                qty = abs(net_up)
                exit_pnl += qty * px_sell
                if heavy_up: u -= qty
                else:        d_ -= qty
                exits += 1; exited = True
        paired = min(u, d_)
        resid = abs(u - d_)
        rp = ((u > d_) == wu) and resid > 0
        pnl = paired + (resid if rp else 0) - uc - dc + exit_pnl
        tot += pnl
        per.append((slug, pnl))
    return tot, blocked_sh, exits, fallback, per

if __name__ == "__main__":
    ERA = 1787256900
    def era(per):
        return sum(p for (s, p) in per if int(s.rsplit('-', 1)[1]) >= ERA)
    print(f"{'policy':26s} {'total$':>8s} {'era$':>7s} {'blkSh':>6s} {'exits':>5s}")
    for nm, pol, D, E in [("baseline", "base", None, None), ("guard1", "g1", None, None),
                          ("F1b alone D=50", "f1b", 50, None),
                          ("G1+F1b D=40", "g1f1b", 40, None), ("G1+F1b D=50", "g1f1b", 50, None),
                          ("G1+F1b D=75", "g1f1b", 75, None)]:
        r = run(pol, D, E)
        print(f"{nm:26s} {r[0]:8.2f} {era(r[4]):+7.2f} {r[1]:6.0f} {r[2]:5d}")
    for D in (50, 75):
        for E in (90, 120, 150):
            r = run("g1f1b_x", D, E)
            print(f"{'G1+F1b+exit D=%d E=%d' % (D, E):26s} {r[0]:8.2f} {era(r[4]):+7.2f} {r[1]:6.0f} {r[2]:5d}")
    for hc in (0.03, 0.05):
        r = run("g1f1b_x", 50, 120, haircut=hc)
        print(f"{'exit50/120 haircut %.2f' % hc:26s} {r[0]:8.2f} {era(r[4]):+7.2f} {r[1]:6.0f} {r[2]:5d}")
