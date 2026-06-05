"""Landscape: pnl45 by entry_vwap x delta_bps buckets (BTC+ETH) to pick meta candidate universe."""
import pandas as pd, numpy as np
m = pd.read_parquet(r"strategy_lab\autoresearch\_data\master_features.parquet")
m = m[m.asset.isin(["BTC", "ETH"])].copy()
print("BTC+ETH rows", len(m))

vb = [0, 0.45, 0.50, 0.55, 0.60, 1.01]
db = [0, 3, 5, 8, 1e9]
m["vbin"] = pd.cut(m.entry_vwap, vb, right=False)
m["dbin"] = pd.cut(m.delta_bps, db, right=False)

def agg(g):
    return pd.Series({"n": len(g), "pnl45": round(g.pnl45.mean(), 3),
                      "pnl60": round(g.pnl60.mean(), 3), "won": round(g.won.mean(), 3)})

print("\n=== by entry_vwap bucket ===")
print(m.groupby("vbin", observed=True).apply(agg, include_groups=False))
print("\n=== by delta bucket ===")
print(m.groupby("dbin", observed=True).apply(agg, include_groups=False))
print("\n=== n by (vwap x delta) ===")
print(m.pivot_table(index="vbin", columns="dbin", values="pnl45", aggfunc="size", observed=True).fillna(0).astype(int))
print("\n=== pnl45 by (vwap x delta) ===")
print(m.pivot_table(index="vbin", columns="dbin", values="pnl45", aggfunc="mean", observed=True).round(2))

# candidate universes of interest
for name, cond in [
    ("vwap<0.55 any-delta", m.entry_vwap < 0.55),
    ("vwap<0.55 d>=3", (m.entry_vwap < 0.55) & (m.delta_bps >= 3)),
    ("vwap<0.55 d>=5 (CELL)", (m.entry_vwap < 0.55) & (m.delta_bps >= 5)),
    ("vwap<0.60 d>=3", (m.entry_vwap < 0.60) & (m.delta_bps >= 3)),
]:
    g = m[cond]
    sh = g.pnl45.mean() / g.pnl45.std() * np.sqrt(len(g)) if g.pnl45.std() > 0 else float("nan")
    print(f"{name:28s} n={len(g):4d} pnl45={g.pnl45.mean():+.3f} won={g.won.mean():.3f} t={sh:.2f} btc/eth={g.asset.value_counts().to_dict()}")
