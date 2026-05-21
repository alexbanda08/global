"""Summarize all full-depth runs in one shot."""
import pandas as pd
import json
from pathlib import Path

paths = [
    "cyclops/_results/p5_full_depth_raw.csv",
    "cyclops/_results/p5_full_depth_p3.csv",
]

for p in paths:
    p = Path(p)
    if not p.exists():
        print(f"MISSING: {p}")
        continue
    df = pd.read_csv(p)
    fired = df[df.fired == True]
    n = len(df)
    nf = len(fired)
    if nf == 0:
        print(f"{p.name}: no fires")
        continue
    wr = fired.won.mean()
    mp = fired.pnl_usd.mean()
    tp = fired.pnl_usd.sum()
    vwap = fired.vwap_entry.mean()
    print(f"{p.name}")
    print(f"  eval={n}  fired={nf}  fire_rate={nf/n:.2%}")
    print(f"  WR={wr:.3f}  mean_pnl=${mp:+.4f}  total=${tp:+.2f}")
    print(f"  mean_vwap=${vwap:.4f}  edge={(wr - vwap)*100:+.2f}pp")
    print(f"  G0 [fired>=10]: {'PASS' if nf >= 10 else 'FAIL'}")
    print(f"  G1 [mean>0]:    {'PASS' if mp > 0 else 'FAIL'}")
    if "won" in fired.columns and "direction" in fired.columns:
        for d in ("Up", "Down"):
            sd = fired[fired.direction == d]
            if len(sd):
                print(f"  {d:5s} n={len(sd):4d} WR={sd.won.mean():.3f} "
                      f"mean=${sd.pnl_usd.mean():+.4f}")
    print()
