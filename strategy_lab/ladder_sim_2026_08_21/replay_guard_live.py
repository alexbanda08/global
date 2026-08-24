# Guard counterfactual REPLAY on our REAL live fills (103 windows, Aug 4-21).
# No fill model at all: take the actual BUY fill sequence per window, apply the
# guard (a side may not fill if it is already >= CAP shares ahead of the other),
# hold to Chainlink settlement, compare against the same hold-to-settle baseline
# with ALL real buys. Sells (cuts) excluded from both books -> isolates the
# guard's effect on ENTRY flow; actual cash w/ sells reported for context only.
import json, csv, math, statistics as st
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
CLIP = 5.0

res = {}
with open(DIR + r"\btc5m_resolutions_2wk.csv", newline="") as fh:
    for row in csv.DictReader(fh):
        res[row["slug"]] = row["outcome"]

recs = json.load(open(DIR + r"\..\wallet_hunt\cache\_pm_portfolio\0x51a5f36d\activity_TRADE_2026_08_21b.json"))
buys = defaultdict(list)
sells = defaultdict(list)
for r in recs:
    slug = r["slug"]
    row = (r["timestamp"], r["outcome"] == "Up", float(r["price"]), float(r["size"]))
    (buys if r["side"] == "BUY" else sells)[slug].append(row)
for d in (buys, sells):
    for v in d.values():
        v.sort()

def settle(up_sh, dn_sh, up_cost, dn_cost, win_up):
    paired = min(up_sh, dn_sh)
    resid = (up_sh - paired) if up_sh > dn_sh else (dn_sh - paired)
    resid_pays = (up_sh > dn_sh) == win_up and resid > 0
    payout = paired + (resid if resid_pays else 0)
    return payout - up_cost - dn_cost, paired, resid, resid_pays

def replay(slug, cap):
    """cap in shares of allowed imbalance BEFORE a fill may land; None = no guard."""
    win_up = res.get(slug) == "Up"
    u_sh = d_sh = u_c = d_c = 0.0
    blocked_sh = blocked_usd = 0.0
    for (t, is_up, px, sh) in buys[slug]:
        s_sh = u_sh if is_up else d_sh
        o_sh = d_sh if is_up else u_sh
        if cap is not None and (s_sh - o_sh) >= cap - 1e-9:
            blocked_sh += sh; blocked_usd += sh * px
            continue
        if is_up: u_sh += sh; u_c += sh * px
        else:     d_sh += sh; d_c += sh * px
    pnl, paired, resid, rp = settle(u_sh, d_sh, u_c, d_c, win_up)
    return dict(pnl=pnl, up=u_sh, dn=d_sh, cost=u_c + d_c, paired=paired,
                resid=resid, resid_won=rp, blocked_sh=blocked_sh, blocked_usd=blocked_usd)

VARIANTS = [("baseline_hold", None), ("guard1 (5sh)", CLIP), ("guard2 (10sh)", 2 * CLIP)]
tot = {n: [] for n, _ in VARIANTS}
per_window = []
for slug in sorted(buys, key=lambda s: int(s.rsplit("-", 1)[1])):
    if slug not in res:
        print("!! no resolution for", slug)
        continue
    row = {"slug": slug}
    for name, cap in VARIANTS:
        r = replay(slug, cap)
        tot[name].append(r)
        row[name] = r
    per_window.append(row)

print(f"windows: {len(per_window)}   (real campaign: 103)")
print(f"{'variant':16s} {'buys$':>8s} {'pnl_hold$':>9s} {'$/w':>7s} {'pair/w':>7s} {'res/w':>6s} "
      f"{'ratio':>6s} {'blockedSh':>9s} {'resWR%':>6s}")
for name, cap in VARIANTS:
    rs = tot[name]
    pnl = [r["pnl"] for r in rs]
    paired = sum(r["paired"] for r in rs); resid = sum(r["resid"] for r in rs)
    rw = [r for r in rs if r["resid"] > 0]
    wr = 100 * sum(1 for r in rw if r["resid_won"]) / len(rw) if rw else 0
    print(f"{name:16s} {sum(r['cost'] for r in rs):8.2f} {sum(pnl):9.2f} {st.mean(pnl):7.3f} "
          f"{paired/len(rs):7.2f} {resid/len(rs):6.2f} {paired/max(resid,1e-9):6.2f} "
          f"{sum(r['blocked_sh'] for r in rs):9.1f} {wr:6.1f}")

# per-window delta of guard1 vs baseline: where does the guard win/lose?
deltas = [(r["guard1 (5sh)"]["pnl"] - r["baseline_hold"]["pnl"], r) for r in per_window]
deltas.sort(key=lambda x: x[0])
dv = [d for d, _ in deltas]
neg = [x for x in dv if x < -1e-9]; pos = [x for x in dv if x > 1e-9]
print(f"\nguard1 delta vs baseline: total {sum(dv):+.2f} | windows helped {len(pos)} (+{sum(pos):.2f}) "
      f"| hurt {len(neg)} ({sum(neg):.2f}) | unchanged {len(dv)-len(pos)-len(neg)}")
print("worst 5 windows for the guard (missed upside):")
for d, r in deltas[:5]:
    b, g = r["baseline_hold"], r["guard1 (5sh)"]
    print(f"  {r['slug']}  d={d:+6.2f}  base up/dn {b['up']:.0f}/{b['dn']:.0f} pnl {b['pnl']:+6.2f}"
          f" -> guard up/dn {g['up']:.0f}/{g['dn']:.0f} pnl {g['pnl']:+6.2f}")
print("best 5 windows for the guard (losses blocked):")
for d, r in deltas[-5:]:
    b, g = r["baseline_hold"], r["guard1 (5sh)"]
    print(f"  {r['slug']}  d={d:+6.2f}  base up/dn {b['up']:.0f}/{b['dn']:.0f} pnl {b['pnl']:+6.2f}"
          f" -> guard up/dn {g['up']:.0f}/{g['dn']:.0f} pnl {g['pnl']:+6.2f}")

# does the opposite side come back? (REAL fills)
print("\n--- opposite-side return after first fill (real fills, all 103 windows) ---")
lags = []; never = 0; onesided_windows = []
for slug in buys:
    seq = buys[slug]
    first_side = seq[0][1]
    opp = [t for (t, u, _, _) in seq if u != first_side]
    if opp:
        lags.append(opp[0] - seq[0][0])
    else:
        never += 1; onesided_windows.append(slug)
lags.sort()
n = len(lags) + never
print(f"windows where opposite side eventually filled: {len(lags)}/{n} ({100*len(lags)/n:.0f}%)")
if lags:
    print(f"lag first->first-opposite fill: median {lags[len(lags)//2]:.0f}s  "
          f"p75 {lags[int(len(lags)*.75)]:.0f}s  p90 {lags[int(len(lags)*.9)]:.0f}s")
print(f"never-returned (one-sided) windows: {never} "
      f"-> baseline pnl {sum(tot['baseline_hold'][i]['pnl'] for i,r in enumerate(per_window) if r['slug'] in onesided_windows):+.2f}"
      f" | guard1 pnl {sum(tot['guard1 (5sh)'][i]['pnl'] for i,r in enumerate(per_window) if r['slug'] in onesided_windows):+.2f}")

json.dump([{ "slug": r["slug"],
             "base_pnl": r["baseline_hold"]["pnl"], "g1_pnl": r["guard1 (5sh)"]["pnl"],
             "g2_pnl": r["guard2 (10sh)"]["pnl"]} for r in per_window],
          open(DIR + r"\replay_per_window.json", "w"))
print("\nwrote replay_per_window.json")
EOF = None
