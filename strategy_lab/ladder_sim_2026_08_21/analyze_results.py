# Analysis of sim_ladder_policies.py output: policy tables, guard dynamics,
# volatility filter study, and hand-checkable debug traces.
import json, gzip, csv, math, statistics as st
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"

rows = json.load(open(DIR + r"\sim_results.json"))
feats = {int(k): v for k, v in json.load(open(DIR + r"\vol_features.json")).items()}

by_pol = defaultdict(list)
for r in rows:
    by_pol[r["policy"]].append(r)

def agg(rs):
    n = len(rs)
    traded = [r for r in rs if r["cost"] > 0]
    pnl = [r["pnl"] for r in traded]
    tot = sum(pnl)
    mean = tot / len(traded) if traded else 0
    sd = st.pstdev(pnl) if len(pnl) > 1 else 0
    t = mean / (sd / math.sqrt(len(pnl))) if sd > 0 else 0
    paired = sum(r["paired"] for r in traded)
    resid = sum(r["resid"] for r in traded)
    both = sum(1 for r in traded if r["up_sh"] > 0 and r["dn_sh"] > 0)
    onesided = [r for r in traded if (r["up_sh"] > 0) != (r["dn_sh"] > 0)]
    pvs = [r["pvs"] for r in traded if r["pvs"]]
    resid_w = [r for r in traded if r["resid"] > 0]
    rw = sum(1 for r in resid_w if r["resid_won"]) / len(resid_w) if resid_w else 0
    cost = sum(r["cost"] for r in traded)
    return dict(windows=n, traded=len(traded), tot=tot, per_w=mean, t=t,
                paired_sh_w=paired / len(traded) if traded else 0,
                resid_sh_w=resid / len(traded) if traded else 0,
                ratio=paired / resid if resid else float("inf"),
                pct_both=100 * both / len(traded) if traded else 0,
                n_onesided=len(onesided),
                onesided_pnl=sum(r["pnl"] for r in onesided),
                pvs_mean=st.mean(pvs) if pvs else 0,
                resid_wr=100 * rw, buy_usd=cost)

print("=" * 118)
print(f"{'policy':22s} {'trad':>5s} {'tot$':>9s} {'$/w':>7s} {'t':>6s} {'pair/w':>7s} "
      f"{'res/w':>6s} {'ratio':>6s} {'%both':>6s} {'1side':>6s} {'1side$':>8s} {'pvs':>6s} {'resWR%':>6s} {'buy$':>9s}")
for name in ["P0_nolimit_fullwin", "P0_nolimit_60s", "P1_guard1_60s", "P1_guard1_60s_s99",
             "P1_guard1_60s_s97", "P2_guard2_60s", "P3_guard1_fullwin",
             "P1_guard1_60s_OPT", "P0_nolimit_60s_OPT"]:
    a = agg(by_pol[name])
    print(f"{name:22s} {a['traded']:5d} {a['tot']:9.2f} {a['per_w']:7.3f} {a['t']:6.2f} "
          f"{a['paired_sh_w']:7.2f} {a['resid_sh_w']:6.2f} {a['ratio']:6.2f} {a['pct_both']:6.1f} "
          f"{a['n_onesided']:6d} {a['onesided_pnl']:8.2f} {a['pvs_mean']:6.3f} {a['resid_wr']:6.1f} {a['buy_usd']:9.0f}")

# ---------------- guard1 dynamics: does the other side ever come back?
print("\n--- P1_guard1_60s: window composition ---")
g = [r for r in by_pol["P1_guard1_60s"] if r["cost"] > 0]
full_pair = [r for r in g if r["paired"] >= 5 and r["resid"] == 0]
part = [r for r in g if r["paired"] >= 5 and r["resid"] > 0]
naked = [r for r in g if r["paired"] == 0]
for lab, ss in [("fully paired (resid 0)", full_pair), ("paired + resid", part), ("one-sided only", naked)]:
    if ss:
        print(f"  {lab:26s} n={len(ss):5d} ({100*len(ss)/len(g):5.1f}%)  pnl {sum(r['pnl'] for r in ss):9.2f} "
              f"(avg {sum(r['pnl'] for r in ss)/len(ss):+.3f}/w)")

# ---------------- vol filter study on the leading policy
print("\n--- volatility features vs per-window PnL ---")
def vol_table(pol_name, feat_key):
    rs = [r for r in by_pol[pol_name] if r["cost"] > 0 and r["slot"] in feats]
    vals = sorted(feats[r["slot"]][feat_key] for r in rs)
    if not vals:
        return
    qs = [vals[int(len(vals) * q) - 1] for q in (0.2, 0.4, 0.6, 0.8)]
    buckets = defaultdict(list)
    for r in rs:
        v = feats[r["slot"]][feat_key]
        b = sum(v > q for q in qs)
        buckets[b].append(r)
    print(f"  {pol_name} by {feat_key} quintile (causal, pre-window):")
    for b in range(5):
        ss = buckets[b]
        if not ss:
            continue
        pnl = [r["pnl"] for r in ss]
        m = st.mean(pnl); sd = st.pstdev(pnl) if len(pnl) > 1 else 0
        t = m / (sd / math.sqrt(len(pnl))) if sd else 0
        lo = vals[0] if b == 0 else qs[b - 1]; hi = qs[b] if b < 4 else vals[-1]
        print(f"    Q{b+1} [{lo:6.1f},{hi:6.1f}]bp n={len(ss):4d} tot {sum(pnl):8.2f} "
              f"avg {m:+.4f} t={t:+5.2f} ratio {sum(r['paired'] for r in ss)/max(1e-9,sum(r['resid'] for r in ss)):5.2f}")

for fk in ("rv5", "rng15", "drift5"):
    vol_table("P1_guard1_60s", fk)
    print()
vol_table("P0_nolimit_60s", "rv5")

# ---------------- lateral (ex-post) diagnostic: in-window range vs pnl
print("\n--- ex-post diagnostic: in-window BTC range vs PnL (P1_guard1_60s) ---")
ts_list, cl_list = [], []
with gzip.open(DIR + r"\btc_1s_2wk.csv.gz", "rt", newline="") as fh:
    rd = csv.reader(fh); next(rd)
    for row in rd:
        ts_list.append(int(row[0]) // 1_000_000); cl_list.append(float(row[1]))
px = dict(zip(ts_list, cl_list))
def inwin_range(slot):
    w = [px[t] for t in range(slot, slot + 300) if t in px]
    if len(w) < 200:
        return None
    return (max(w) - min(w)) / w[0] * 1e4
rs = [r for r in by_pol["P1_guard1_60s"] if r["cost"] > 0]
pairs = [(inwin_range(r["slot"]), r) for r in rs]
pairs = [(v, r) for v, r in pairs if v is not None]
vals = sorted(v for v, _ in pairs)
qs = [vals[int(len(vals) * q) - 1] for q in (0.2, 0.4, 0.6, 0.8)]
buckets = defaultdict(list)
for v, r in pairs:
    buckets[sum(v > q for q in qs)].append(r)
for b in range(5):
    ss = buckets[b]
    pnl = [r["pnl"] for r in ss]
    lo = vals[0] if b == 0 else qs[b-1]; hi = qs[b] if b < 4 else vals[-1]
    print(f"  Q{b+1} [{lo:6.1f},{hi:6.1f}]bp n={len(ss):4d} tot {sum(pnl):8.2f} avg {st.mean(pnl):+.4f} "
          f"ratio {sum(r['paired'] for r in ss)/max(1e-9,sum(r['resid'] for r in ss)):5.2f}")

# ---------------- causal filter proposal: skip/scale by rv5 threshold
print("\n--- causal filter: P&L retained if we SKIP windows above rv5 percentile ---")
rs1 = [r for r in by_pol["P1_guard1_60s"] if r["cost"] > 0 and r["slot"] in feats]
sv = sorted(feats[r["slot"]]["rv5"] for r in rs1)
for pct in (50, 60, 70, 80, 90, 100):
    thr = sv[min(len(sv) - 1, int(len(sv) * pct / 100) - 1)]
    kept = [r for r in rs1 if feats[r["slot"]]["rv5"] <= thr]
    drop = [r for r in rs1 if feats[r["slot"]]["rv5"] > thr]
    kp = [r["pnl"] for r in kept]
    m = st.mean(kp); sd = st.pstdev(kp) if len(kp) > 1 else 0
    t = m / (sd / math.sqrt(len(kp))) if sd else 0
    print(f"  keep rv5<=p{pct:3d} ({thr:6.1f}bp): n={len(kept):4d} tot {sum(kp):8.2f} avg {m:+.4f} "
          f"t={t:+5.2f} | dropped pnl {sum(r['pnl'] for r in drop):8.2f}")
