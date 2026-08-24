# Displacement-filter counterfactuals on our REAL live fills (109 windows incl today).
# F1a blunt:  block loser-side BUY when |d| >= D
# F1b smart:  block loser-side BUY when |d| >= D AND it increases imbalance
#             (pair completions exempt) — the deployable form
# G1+F1b:     stacked with the 1-clip guard (yesterday's validated rule)
# F2 exit:    on top of G1+F1b, at elapsed>=E if net side X is loser by |d|>=D,
#             sell the excess at (last X print - 1 tick). Pros never sell; we test.
import json, gzip, csv, math
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
CLIP = 5.0

# --- price lookup
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

# --- resolutions (fallback: binance sign for missing)
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

# --- our fills
recs = json.load(open(DIR + r"\..\wallet_hunt\cache\_pm_portfolio\0x51a5f36d\activity_TRADE_2026_08_21c.json"))
buys = defaultdict(list)
for r in recs:
    if r["side"] == "BUY" and r["slug"].startswith("btc-updown-5m-"):
        buys[r["slug"]].append((r["timestamp"], r["outcome"] == "Up",
                                float(r["price"]), float(r["size"])))
for v in buys.values():
    v.sort()

# --- loser-token last print per window (for F2 exit price)
need = set(buys)
prints = defaultdict(list)      # slug -> [(t, is_up, px)]
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

def run(policy, D=None, E=None):
    """policy in {base, g1, f1a, f1b, g1f1b, g1f1b_x}"""
    tot = 0.0; n_ok = 0; blocked_sh = 0.0; exits = 0; fallback = 0
    per = []
    for slug, seq in buys.items():
        start = int(slug.rsplit("-", 1)[1])
        wu, fb = winner_up(slug, start)
        fallback += fb
        u = d_ = uc = dc = 0.0
        for (t, is_up, prc, sh) in seq:
            el = t - start
            b0, b = px_at(start), px_at(t)
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
        # F2 exit scan
        exit_pnl = 0.0
        if policy == "g1f1b_x" and E is not None:
            for el in range(E, 296, 5):
                t = start + el
                b0, b = px_at(start), px_at(t)
                if not (b0 and b):
                    continue
                disp = b - b0
                net_up = u - d_
                if abs(disp) < D or abs(net_up) < 1e-9:
                    continue
                heavy_up = net_up > 0
                if heavy_up == (disp > 0):
                    continue            # heavy side is the leader -> no exit
                lp = last_print(slug, heavy_up, t)
                if lp is None:
                    continue
                px_sell = max(lp - 0.01, 0.01)
                qty = abs(net_up)
                exit_pnl += qty * px_sell
                if heavy_up: u -= qty
                else:        d_ -= qty
                exits += 1
                break
        paired = min(u, d_)
        resid = abs(u - d_)
        rp = ((u > d_) == wu) and resid > 0
        pnl = paired + (resid if rp else 0) - uc - dc + exit_pnl
        tot += pnl; n_ok += 1
        per.append((slug, pnl))
    return tot, n_ok, blocked_sh, exits, fallback, per

print(f"{'policy':22s} {'total$':>8s} {'blockedSh':>9s} {'exits':>5s}")
base = run("base")
print(f"{'baseline_hold':22s} {base[0]:8.2f} {base[2]:9.0f} {base[3]:5d}   (windows {base[1]}, binance-fallback winners {base[4]})")
g1 = run("g1")
print(f"{'guard1':22s} {g1[0]:8.2f} {g1[2]:9.0f}")
for D in (40, 50, 75, 100):
    r = run("f1a", D)
    print(f"{'F1a blunt D=%d' % D:22s} {r[0]:8.2f} {r[2]:9.0f}")
for D in (40, 50, 75, 100):
    r = run("f1b", D)
    print(f"{'F1b smart D=%d' % D:22s} {r[0]:8.2f} {r[2]:9.0f}")
for D in (40, 50, 75, 100):
    r = run("g1f1b", D)
    print(f"{'G1+F1b D=%d' % D:22s} {r[0]:8.2f} {r[2]:9.0f}")
for D in (50, 75):
    for E in (90, 120, 150):
        r = run("g1f1b_x", D, E)
        print(f"{'G1+F1b+exit D=%d E=%d' % (D, E):22s} {r[0]:8.2f} {r[2]:9.0f} {r[3]:5d}")

# era split for the leading configs
def era(per, lo):
    return sum(p for (s, p) in per if int(s.rsplit('-', 1)[1]) >= lo)
ERA = 1787256900
print("\ncompliant era (r5->today):")
for nm, r in [("baseline", base), ("guard1", g1), ("G1+F1b D=50", run("g1f1b", 50)),
              ("G1+F1b D=75", run("g1f1b", 75)),
              ("G1+F1b+exit 75/120", run("g1f1b_x", 75, 120))]:
    print(f"  {nm:20s} {era(r[5], ERA):+8.2f}")
