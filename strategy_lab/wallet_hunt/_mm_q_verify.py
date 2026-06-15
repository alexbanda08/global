"""INDEPENDENT RE-VERIFICATION of the tighter-Q sweep + boundary extension (Q=2,3).
Operator mandate: review everything, reanalyze 2x, side-by-side, trustworthy.
(1) Re-derive net_pnl from RAW columns (sh/vwap/outcome) — do NOT trust the engine's stored net_pnl.
(2) Fresh independent bootstrap CI (different seed/method) + median + %positive + ex2/ex5 (tail-robustness).
(3) Extend the grid to Q=2,3 (boundary: is Q=5 optimal or does it keep improving / collapse?).
"""
import sys, os, time
sys.path.insert(0, "data/v4/canonical"); sys.path.insert(0, os.path.dirname(__file__))
import importlib.util, numpy as np, pandas as pd

spec = importlib.util.spec_from_file_location("inv", os.path.join(os.path.dirname(__file__), "_mm_inv_engine.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
CACHE = os.path.join(os.path.dirname(__file__), "cache")
REB = 0.0015

# outcome map for independent PnL re-derivation (engine loader: has slug, slot_start_s, slot_start_us, outcome)
res = m.load_resolutions(); OUT = dict(zip(res.slug, res.outcome.astype(str).str.lower()))

def rederive_net(row):
    """Independent re-derivation of per-slug net PnL from raw columns + true outcome."""
    su, sd = row.sh_up, row.sh_dn
    if su <= 0 and sd <= 0: return 0.0
    vu = row.vwap_up if pd.notna(row.vwap_up) else 0.0
    vd = row.vwap_dn if pd.notna(row.vwap_dn) else 0.0
    paired = min(su, sd); pvs = vu + vd
    paired_pnl = paired * (1.0 - pvs)
    ru, rd = su - paired, sd - paired
    won_up = OUT.get(row.slug, "") == "up"
    res_pnl = (ru * (1 - vu) - rd * vd) if won_up else (rd * (1 - vd) - ru * vu)
    return paired_pnl + res_pnl + (su + sd) * REB

def boot_ci(x, nb=5000, seed=123):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    rng = np.random.default_rng(seed)
    bs = rng.choice(x, (nb, len(x)), replace=True).mean(axis=1)
    return np.percentile(bs, 2.5), np.percentile(bs, 97.5)

def analyze(R, Q, src):
    fi = R[(R.sh_up > 0) | (R.sh_dn > 0)].copy()
    oos = fi[fi.is_oos == "OOS"]
    # independent re-derivation
    rederived = oos.apply(rederive_net, axis=1).to_numpy()
    stored = oos.net_pnl.to_numpy()
    maxdiff = np.nanmax(np.abs(rederived - stored)) if len(oos) else 0.0
    net = rederived  # USE the independently re-derived values
    ci = boot_ci(net)
    order = np.argsort(np.abs(net))
    ex2 = net[order[:-2]].mean(); ex5 = net[order[:-5]].mean()
    return dict(Q=Q, src=src, n=len(oos), accounting_maxdiff=maxdiff,
                mean=net.mean(), median=np.median(net), ci_lo=ci[0], ci_hi=ci[1],
                ex2=ex2, ex5=ex5, pct_pos=100*(net > 0).mean(),
                resid=oos.residual_pnl.mean(), paired=oos.paired_pnl.mean(), pvs=oos[oos.pvs.notna()].pvs.median())

def run_q(Q):
    ck = os.path.join(CACHE, f"_mm_q{Q}_full.parquet")
    if os.path.exists(ck): return pd.read_parquet(ck), "cached"
    # run fresh
    print(f"  running Q={Q} fresh...", flush=True)
    slug_set = set(res.slug); tob = run_q._tob; trades = run_q._tr
    slot_map = dict(zip(res.slug, res.slot_start_s)); out_map = dict(zip(res.slug, res.outcome))
    recs = []
    for slug in sorted(res.slug):
        ss = slot_map.get(slug)
        if ss is None: continue
        wu = str(out_map.get(slug, "")).lower() == "up"
        o = m.sim_slug(tob.get((slug, "Up")), trades.get((slug, "Up")), tob.get((slug, "Down")),
                       trades.get((slug, "Down")), ss, -3600, 350.0, float(Q), 0.05, use_upper=False)
        p = m.slug_pnl(o, wu); p["slug"] = slug; p["slot_us"] = int(ss * 1e6)
        p["n_fills_up"] = o["n_fills_up"]; p["n_fills_dn"] = o["n_fills_dn"]
        p["is_oos"] = "IS" if ss * 1e6 < m.IS_CUTOFF_US else "OOS"; p["Q"] = Q
        recs.append(p)
    R = pd.DataFrame(recs); R.to_parquet(ck, index=False); return R, "fresh"

def main():
    t0 = time.time()
    print("="*78); print("INDEPENDENT RE-VERIFICATION + BOUNDARY (Q=2,3)"); print("="*78)
    # need engine data only if Q=2,3 not cached
    need_fresh = any(not os.path.exists(os.path.join(CACHE, f"_mm_q{Q}_full.parquet")) for Q in [2, 3])
    if need_fresh:
        print("loading data for boundary cells...", flush=True)
        ss = set(res.slug); run_q._tob = m.load_books(ss); run_q._tr = m.load_trades(ss)
        print(f"  loaded t={time.time()-t0:.0f}s", flush=True)
    rows = []
    for Q in [2, 3, 5, 8, 12, 16, 20]:
        R, src = run_q(Q)
        a = analyze(R, Q, src); rows.append(a)
        print(f"\nQ={Q:>2} [{src}] n={a['n']}  ACCT_MAXDIFF={a['accounting_maxdiff']:.4f}")
        print(f"   OOS net: mean={a['mean']:+.3f} median={a['median']:+.3f} CI95=[{a['ci_lo']:+.3f},{a['ci_hi']:+.3f}] "
              f"ex2={a['ex2']:+.3f} ex5={a['ex5']:+.3f} %pos={a['pct_pos']:.1f}%")
        print(f"   resid={a['resid']:+.2f} paired={a['paired']:+.2f} pvs={a['pvs']:.3f}")
    print("\n" + "="*78); print("CURVE (OOS net vs Q, independently re-derived)"); print("="*78)
    sm = pd.DataFrame(rows).sort_values("Q")
    for _, r in sm.iterrows():
        go = (r.ci_lo > 0) and (r.ex2 > 0)
        print(f"  Q={int(r.Q):>2}: mean={r['mean']:+.3f} med={r['median']:+.3f} CI[{r.ci_lo:+.3f},{r.ci_hi:+.3f}] "
              f"ex2={r.ex2:+.3f} ex5={r.ex5:+.3f} %pos={r.pct_pos:.0f}% resid={r.resid:+.2f} -> {'GO' if go else 'no'}")
    sm.to_parquet(os.path.join(CACHE, "_mm_q_verify.parquet"), index=False)
    maxacct = sm.accounting_maxdiff.max()
    print(f"\n  ACCOUNTING CROSS-CHECK: max |re-derived − stored| over all cells = {maxacct:.5f} "
          f"({'PASS — engine accounting verified' if maxacct < 1e-6 else 'MISMATCH — investigate'})")
    print(f"  total t={time.time()-t0:.0f}s"); print("="*78)

if __name__ == "__main__":
    main()
