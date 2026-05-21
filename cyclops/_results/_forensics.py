"""Quick forensics on p2_full_21d.csv to decide STOP vs investigate further."""
import pandas as pd, numpy as np

df = pd.read_csv("cyclops/_results/p2_full_21d.csv")
n = len(df)
fired = df[df.fired == True].copy()
nf = len(fired)
print(f"eval={n}  fired={nf}  fire_rate={nf/n:.1%}")
print(f"WR={fired.won.mean():.3f}  mean_pnl=${fired.pnl_usd.mean():+.4f}")
print(f"mean entry vwap=${fired.vwap_entry.mean():.4f}  median=${fired.vwap_entry.median():.4f}")
print(f"breakeven WR at mean vwap: {fired.vwap_entry.mean():.3f}")
print()

print("=== Per-direction split ===")
print(fired.groupby("direction").agg(n=("pnl_usd", "size"), wr=("won", "mean"),
                                     mean_pnl=("pnl_usd", "mean"),
                                     mean_vwap=("vwap_entry", "mean"),
                                     total=("pnl_usd", "sum")))
print()

print("=== Solo-axis predictiveness (every evaluation, ignoring conflict) ===")
for axis in ("v_trend", "v_levels", "v_momentum"):
    sub = df[df[axis] != 0].copy()
    if sub.empty:
        continue
    sub["pred"] = np.where(sub[axis] > 0, "Up", "Down")
    sub["hit"] = (sub["pred"] == sub.outcome_truth).astype(int)
    print(f"  {axis:12s}  n={len(sub):5d}  hit_rate={sub.hit.mean():.3f}")
print()

print("=== Coherent-vote-count edge breakdown (fired only) ===")
fired["n_pos"] = ((fired.v_trend > 0).astype(int) +
                  (fired.v_levels > 0).astype(int) +
                  (fired.v_momentum > 0).astype(int))
fired["n_neg"] = ((fired.v_trend < 0).astype(int) +
                  (fired.v_levels < 0).astype(int) +
                  (fired.v_momentum < 0).astype(int))
fired["n_coherent"] = fired.n_pos + fired.n_neg
print(fired.groupby("n_coherent").agg(n=("pnl_usd", "size"), wr=("won", "mean"),
                                      mean_pnl=("pnl_usd", "mean")))
print()

print("=== Counter-direction trade (sign-flip diagnostic) ===")
# If we'd traded the OPPOSITE direction, what would WR be?
flip_won = (fired.direction == "Up").astype(int) ^ (fired.outcome_truth == "Up").astype(int)
flip_wr = flip_won.mean()
print(f"  flipped-direction WR: {flip_wr:.3f}  (vs as-built {fired.won.mean():.3f})")
print()

print("=== Skip reason counts ===")
print(df[~df.fired].skip_reason.value_counts().head(10))
