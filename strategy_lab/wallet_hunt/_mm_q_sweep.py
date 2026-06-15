"""TIGHTER GLT-CAP SWEEP — the one untested knob that hits the proven binding constraint (residual drag).
Re-audit (B945_SESSION_REAUDIT_2026_06_13) showed: OOS killer is residual drag (−$4.53/slug) > paired
gain (+$3.89), NOT flow capture. GLT Q is the dominant residual lever (Q∞→20 moved net −9.46→−0.31).
We only ever tested Q∈{20,50,100,∞}. This sweeps the TIGHTER region Q∈{5,8,12,16,20}.

PRE-REGISTERED (before any run):
  - Strategy = MAKER-ONLY (corrected; taker-completion proven to never fire). γ=0.05, budget=$350,
    full-band, $5 clips, offset −3600s, FIFO lower bound. Same as the validated config except Q.
  - Grid: Q ∈ {5, 8, 12, 16, 20} (20 = known anchor for continuity). 5 cells.
  - Full universe, IS (Apr22–May20) / OOS (May21–Jun11) split.
  - DECISION RULE: GO if any Q gives OOS net CI95 lower bound > 0 AND ex-top2 > 0.
  - FAITHFULNESS CHECK: a winning Q must still resemble b945 (pvs ≳ 0.95, fills/side not collapsed);
    if tighter Q wins only by deviating from his fingerprint, flag it as a DIFFERENT strategy.
  - Reconcile every cell vs b945 GT (pvs 0.967, net +$3.18/slug median, fills/side 44).
Checkpoints per Q to cache/_mm_q{Q}_full.parquet so a crash can't lose work.
"""
import sys, os, time
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, os.path.dirname(__file__))
import importlib.util
import numpy as np, pandas as pd

spec = importlib.util.spec_from_file_location("inv", os.path.join(os.path.dirname(__file__), "_mm_inv_engine.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

Q_GRID = [5, 8, 12, 16, 20]
GAMMA, BUDGET, OFFSET = 0.05, 350.0, -3600
CACHE = os.path.join(os.path.dirname(__file__), "cache")

def summarize(R, label):
    fi = R[(R.sh_up > 0) | (R.sh_dn > 0)].copy()
    if len(fi) == 0:
        return dict(label=label, n=0)
    tot = fi.sh_up.sum() + fi.sh_dn.sum()
    pf = 2 * fi.paired.sum() / tot if tot > 0 else 0.
    pvs = fi[fi.pvs.notna()].pvs.median()
    fills_sd = (fi.n_fills_up + fi.n_fills_dn).mean() / 2
    net = fi.net_pnl.to_numpy()
    ci = m.boot(net, nb=3000)
    ex2 = net[np.argsort(np.abs(net))[:-2]].mean() if len(net) > 2 else np.nan
    # slug-cluster CI (block bootstrap by slug already 1 row/slug here, so == net CI)
    return dict(label=label, n=len(fi), pair_frac=pf, pvs=pvs, fills_sd=fills_sd,
                paired=fi.paired_pnl.mean(), resid=fi.residual_pnl.mean(),
                rebate=fi.rebate_pnl.mean(), net_mean=net.mean(), net_med=np.median(net),
                ci_lo=ci[0], ci_hi=ci[1], ex2=ex2)

def pr(s, pfx="    "):
    if not s or s.get("n", 0) == 0:
        print(pfx + "(no fills)"); return
    print(f"{pfx}n={s['n']} pvs={s['pvs']:.3f} pf={100*s['pair_frac']:.1f}% fills/sd={s['fills_sd']:.1f} "
          f"paired={s['paired']:+.2f} resid={s['resid']:+.2f} reb={s['rebate']:+.2f}")
    print(f"{pfx}net_mean={s['net_mean']:+.2f} net_med={s['net_med']:+.2f} "
          f"CI95=[{s['ci_lo']:+.2f},{s['ci_hi']:+.2f}] ex2={s['ex2']:+.2f}")

def main():
    t0 = time.time()
    print("="*74); print("TIGHTER GLT-CAP SWEEP (maker-only)"); print("="*74)
    print(f"PRE-REG: Q∈{Q_GRID} γ={GAMMA} budget=${BUDGET:.0f} offset={OFFSET}s FIFO maker-only")
    print(f"DECISION: GO if any Q OOS CI95 lo>0 AND ex2>0")
    print(f"B945 GT: pvs={m.GT_PVS:.3f} net=+${m.GT_NET:.2f}/slug(med) fills/sd={m.GT_FILLS_SD:.0f}")
    res = m.load_resolutions()
    res_IS = res[res.slot_start_us < m.IS_CUTOFF_US]; res_OOS = res[res.slot_start_us >= m.IS_CUTOFF_US]
    print(f"slugs {len(res)} IS={len(res_IS)} OOS={len(res_OOS)}", flush=True)
    slug_set = set(res.slug)
    tob = m.load_books(slug_set); print(f"books {len(tob)} t={time.time()-t0:.0f}s", flush=True)
    trades = m.load_trades(slug_set); print(f"trades {len(trades)} t={time.time()-t0:.0f}s", flush=True)

    slot_map = dict(zip(res.slug, res.slot_start_s)); out_map = dict(zip(res.slug, res.outcome))
    all_slugs = sorted(res.slug.tolist())

    summary_rows = []
    for Q in Q_GRID:
        ckpt = os.path.join(CACHE, f"_mm_q{Q}_full.parquet")
        if os.path.exists(ckpt):
            print(f"\n--- Q={Q}: cached ---", flush=True); R = pd.read_parquet(ckpt)
        else:
            print(f"\n--- Q={Q}: running full universe ---", flush=True)
            recs = []
            for slug in all_slugs:
                slot_s = slot_map.get(slug)
                if slot_s is None: continue
                won_up = str(out_map.get(slug, "")).lower() == "up"
                o = m.sim_slug(tob.get((slug, "Up")), trades.get((slug, "Up")),
                               tob.get((slug, "Down")), trades.get((slug, "Down")),
                               slot_s, OFFSET, BUDGET, float(Q), GAMMA, use_upper=False)
                p = m.slug_pnl(o, won_up)
                p["slug"] = slug; p["slot_us"] = int(slot_s * 1e6)
                p["n_fills_up"] = o["n_fills_up"]; p["n_fills_dn"] = o["n_fills_dn"]
                p["is_oos"] = "IS" if slot_s * 1e6 < m.IS_CUTOFF_US else "OOS"
                recs.append(p)
            R = pd.DataFrame(recs); R["Q"] = Q
            R.to_parquet(ckpt, index=False)
            print(f"    saved {ckpt}  t={time.time()-t0:.0f}s", flush=True)
        sIS = summarize(R[R.is_oos == "IS"], f"Q{Q}_IS"); sO = summarize(R[R.is_oos == "OOS"], f"Q{Q}_OOS")
        print(f"  IS :"); pr(sIS); print(f"  OOS:"); pr(sO)
        go = (sO.get("ci_lo", -9) > 0) and (sO.get("ex2", -9) > 0)
        print(f"  -> Q={Q} OOS verdict: {'GO' if go else 'NO-GO'}")
        summary_rows.append(dict(Q=Q, **{f"IS_{k}": v for k, v in sIS.items() if k != 'label'},
                                 **{f"OOS_{k}": v for k, v in sO.items() if k != 'label'}, GO=go))

    print("\n" + "="*74); print("SUMMARY — OOS net by Q (residual-drag lever)"); print("="*74)
    sm = pd.DataFrame(summary_rows)
    for _, r in sm.iterrows():
        print(f"  Q={int(r.Q):>2}: IS net={r.get('IS_net_mean',float('nan')):+.2f} pvs={r.get('IS_pvs',float('nan')):.3f} | "
              f"OOS net={r.get('OOS_net_mean',float('nan')):+.2f} [{r.get('OOS_ci_lo',float('nan')):+.2f},{r.get('OOS_ci_hi',float('nan')):+.2f}] "
              f"ex2={r.get('OOS_ex2',float('nan')):+.2f} resid={r.get('OOS_resid',float('nan')):+.2f} paired={r.get('OOS_paired',float('nan')):+.2f} "
              f"pvs={r.get('OOS_pvs',float('nan')):.3f} fills/sd={r.get('OOS_fills_sd',float('nan')):.0f} -> {'GO' if r.GO else 'NO-GO'}")
    sm.to_parquet(os.path.join(CACHE, "_mm_q_sweep_summary.parquet"), index=False)
    any_go = sm.GO.any()
    print(f"\n  ANY Q GO: {any_go}")
    print(f"  total t={time.time()-t0:.0f}s"); print("="*74)

if __name__ == "__main__":
    main()
