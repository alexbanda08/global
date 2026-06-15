"""Analyze the FVG grid: WHERE does the edge live (offset), does a gap threshold + cheap-gate beat noise,
   and is there a MID-WINDOW pocket? Reads scalp_fvg_grid_fixed_2026_06_10{TAG}.parquet."""
import sys, os, glob
from pathlib import Path
import numpy as np, pandas as pd
np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global"); RES = ROOT / "strategy_lab/directional/_results"
G = pd.concat([pd.read_parquet(f) for f in glob.glob(str(RES / "scalp_fvg_grid_fixed_2026_06_10*.parquet"))], ignore_index=True)
G = G.drop_duplicates(["coin", "tf", "slug", "off"]).reset_index(drop=True)
print(f"grid rows={len(G)}  coins={G.coin.value_counts().to_dict()}  tfs={G.tf.value_counts().to_dict()}")

def boot(v, nb=4000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
def cell(v):
    v = np.asarray(v)
    if len(v) < 5: return f"n={len(v):4d} (few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={(v>0).mean():.2f}"

THR = float(os.environ.get("THR", "0.08"))
for (coin, tf), g in G.groupby(["coin", "tf"]):
    print(f"\n################ {coin} {tf} (windows~{g.slug.nunique()}) ################")
    print("--- per-offset, |gap|>=%.2f, ALL vs cheap(ev<0.55) ---" % THR)
    for off in sorted(g.off.unique()):
        s = g[(g.off == off) & (g.abs_gap >= THR)]
        sc = s[s.ev < 0.55]
        print(f"  +{off:4d}s | ALL {cell(s.pnl60.values):60s} | cheap {cell(sc.pnl60.values)}")
    # first-cross one-shot (realistic): open-first-cross vs MID-only-first-cross
    print("--- first-cross one-shot per window (threshold sweep), cheap-gated ---")
    for thr in [0.04, 0.06, 0.08, 0.10, 0.12]:
        q = g[g.abs_gap >= thr].sort_values(["slug", "off"])
        fc = q.drop_duplicates("slug", keep="first")            # global first cross
        fcc = fc[fc.ev < 0.55]
        midq = q[q.off >= 120].drop_duplicates("slug", keep="first")  # first cross AMONG mid offsets
        midc = midq[midq.ev < 0.55]
        print(f"  thr={thr:.2f} | firstcross cheap {cell(fcc.pnl60.values):58s} | MIDfirstcross cheap {cell(midc.pnl60.values)}")

# pooled mid-window verdict (off>=120, cheap, gap>=THR), per coin
print(f"\n===== MID-WINDOW VERDICT (off>=120, ev<0.55, |gap|>={THR}) per coin-tf =====")
for (coin, tf), g in G.groupby(["coin", "tf"]):
    m = g[(g.off >= 120) & (g.ev < 0.55) & (g.abs_gap >= THR)]
    print(f"  {coin} {tf}: {cell(m.pnl60.values)}")
print("\nREAD: edge exists at an offset/threshold only if cheap-gated $/tr>0 with CI>0. MID pocket needs off>=120 cell CI>0.")
