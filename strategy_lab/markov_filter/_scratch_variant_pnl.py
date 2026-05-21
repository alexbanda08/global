"""Quick: which exit variant has the best per-fire baseline?"""
import pandas as pd
df = pd.read_csv('data/v4/canonical/_results/full_universe_live_mimic_2026_05_16/per_trade.csv')
f = df[df['fired']].copy()
f["won"] = ((f["signal"] == "UP") & (f["outcome"] == "Up")) | \
          ((f["signal"] == "DOWN") & (f["outcome"] == "Down"))
print('Per-variant baseline (fired only):')
rows = []
for v in f['variant'].unique():
    sub = f[f['variant'] == v]
    rows.append({
        "variant": v, "n": len(sub),
        "wr": round(sub["won"].mean() * 100, 2),
        "avg_pnl": round(sub["pnl"].mean(), 3),
        "sum_pnl": round(sub["pnl"].sum(), 2),
    })
out = pd.DataFrame(rows).sort_values("sum_pnl", ascending=False)
print(out.to_string(index=False))
