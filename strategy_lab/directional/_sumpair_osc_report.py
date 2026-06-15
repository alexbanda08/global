"""Report for the oscillation-harvest parquet (correct OOS split + net/$ + ex-top2 + control).
Reads the saved parquet; no re-run. Usage: py _sumpair_osc_report.py [parquet_path]"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from scalp_fill_lib_2026_06_10 import boot, cell   # noqa: E402

IS_HI = pd.Timestamp("2026-05-21", tz="UTC").value // 1000   # us boundary
THRS = [2.0, 3.0, 5.0]

p = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    ROOT / "strategy_lab/directional/_results/sumpair_oscillation_harvest_2026_06_13.parquet"
R = pd.read_parquet(p)
R["oos"] = R.slot_start_us >= IS_HI
print(f"loaded {len(R)} rows  coins={sorted(R.coin.unique())} tf={sorted(R.tf.unique())}")
print(f"IS slugs(thr3)={(~R[R.thr==3].oos).sum()}  OOS slugs(thr3)={R[R.thr==3].oos.sum()}")


def stat(v):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    if len(v) < 5:
        return f"n={len(v):4d} (few)", np.nan, (np.nan, np.nan)
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    return f"n={len(v):5d} $/slug={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]", v.mean(), (lo, hi)


print("\n" + "=" * 92)
print("FEASIBILITY (per THR; over slugs where ANY side fired):")
for thr in THRS:
    g = R[R.thr == thr]
    fired = g[~g.neither]
    pc = g.paircost.dropna()
    print(f"  THR={thr:.0f}bp fired={len(fired):5d} both={g.both.sum():5d} "
          f"({g.both.sum()/max(len(fired),1):.1%}) only_up={g.only_up.sum()} only_dn={g.only_dn.sum()} "
          f"neither={g.neither.sum()}  | paircost med={pc.median():.4f} %<1={(pc<1).mean():.1%} (n={len(pc)})")

print("\n" + "=" * 92)
print("ARM A (oscillation-harvest, hold pair) net/slug over FIRED slugs + vs deployed +60s scalp:")
for thr in THRS:
    g = R[(R.thr == thr) & (~R.neither)].copy()
    for scope, gg in (("ALL", g), ("IS ", g[~g.oos]), ("OOS", g[g.oos])):
        s, _, _ = stat(gg.arm_a_pnl.values)
        print(f"  THR={thr:.0f}bp {scope}: {s}")
    # vs control paired (ALL + OOS)
    for scope, gg in (("ALL", g), ("OOS", g[g.oos])):
        d = (gg.arm_a_pnl - gg.ctrl).values
        d = d[np.isfinite(d)]
        if len(d) >= 5:
            lo, hi = boot(d)
            print(f"           [{scope}] ARM_A - CTRL(+60s) paired: n={len(d)} mean={d.mean():+.4f} "
                  f"CI=[{lo:+.4f},{hi:+.4f}]   CTRL net/slug={gg.ctrl.mean():+.4f}")
    # ex-top2 OOS robustness
    oos = g[g.oos].arm_a_pnl.values
    oos = oos[np.isfinite(oos)]
    if len(oos) > 3:
        ex = np.sort(oos)[:-2]
        print(f"           [OOS] ex-top2 net/slug={ex.mean():+.4f} (n={len(ex)})")
    # net per $ deployed (capital-normalized) OOS
    oosg = g[g.oos]
    cost = oosg.cost_total.values
    pnl = oosg.arm_a_pnl.values
    m = np.isfinite(cost) & np.isfinite(pnl) & (cost > 0)
    if m.sum() >= 5:
        roi = (pnl[m] / cost[m])
        print(f"           [OOS] net per $ deployed: mean={roi.mean():+.4f}  "
              f"(total pnl {pnl[m].sum():+.1f} / total cost {cost[m].sum():.1f} = {pnl[m].sum()/cost[m].sum():+.4f})")

print("\n" + "=" * 92)
print("PER-COIN x TF (THR=3, fired slugs):  ALL | OOS")
g3 = R[(R.thr == 3.0) & (~R.neither)]
for (c, tf), gg in g3.groupby(["coin", "tf"]):
    sa, _, _ = stat(gg.arm_a_pnl.values)
    so, _, _ = stat(gg[gg.oos].arm_a_pnl.values)
    print(f"  {c} {tf}: ALL {sa}  both%={gg.both.mean():.1%}")
    print(f"            OOS {so}")
