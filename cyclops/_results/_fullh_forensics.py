"""Compare degraded-momentum (P2) vs full-depth-momentum (P5) results.

Goal: did adding streaming OB + trades change WHICH trades fire and WHICH axes
agree with the truth?
"""
import pandas as pd
import numpy as np

df = pd.read_csv("cyclops/_results/p5_full_depth_raw.csv")
n = len(df)
fired = df[df.fired == True].copy()
print(f"=== Full-depth raw (no filters) ===")
print(f"eval={n}  fired={len(fired)}  fire_rate={len(fired)/n:.2%}")
print(f"WR={fired.won.mean():.3f}  mean_pnl=${fired.pnl_usd.mean():+.4f}  total=${fired.pnl_usd.sum():+.2f}")
print(f"mean vwap=${fired.vwap_entry.mean():.4f}  breakeven={fired.vwap_entry.mean():.3f}")
print()

print("=== Per-axis predictiveness (full universe, ignoring filter) ===")
for ax in ("v_trend", "v_levels", "v_momentum"):
    sub = df[df[ax] != 0].copy()
    if sub.empty:
        continue
    sub["pred"] = np.where(sub[ax] > 0, "Up", "Down")
    sub["hit"] = (sub.pred == sub.outcome_truth).astype(int)
    print(f"  {ax:12s}  n={len(sub):5d}  hit={sub.hit.mean():.3f}")
print()

print("=== Momentum components (full-depth) ===")
print(f"  imb_l5    : mean={df.mom_imb_l5.mean():+.4f}  std={df.mom_imb_l5.std():.4f}  "
      f"nz={(df.mom_imb_l5 != 0).sum()}")
print(f"  cvd_norm  : mean={df.mom_cvd_norm.mean():+.4f}  std={df.mom_cvd_norm.std():.4f}  "
      f"nz={(df.mom_cvd_norm != 0).sum()}")
print(f"  aggressor : mean={df.mom_aggressor.mean():+.4f}  std={df.mom_aggressor.std():.4f}  "
      f"nz={(df.mom_aggressor != 0).sum()}")
print()

print("=== Tuple distribution (fired) — full-depth ===")
print(fired.groupby(["v_trend", "v_levels", "v_momentum"]).agg(
    n=("pnl_usd", "size"), wr=("won", "mean"),
    mean_vwap=("vwap_entry", "mean"),
    mean_pnl=("pnl_usd", "mean"),
).round(3))
print()

print("=== Trend-only and Levels-only on FIRED trades (full-depth) ===")
for ax in ("v_trend", "v_levels"):
    sub_fired = fired[fired[ax] != 0]
    if not sub_fired.empty:
        sub_fired = sub_fired.copy()
        sub_fired["pred"] = np.where(sub_fired[ax] > 0, "Up", "Down")
        hit = (sub_fired.pred == sub_fired.outcome_truth).mean()
        print(f"  fired-with-{ax}!=0: n={len(sub_fired)}  hit={hit:.3f}")
