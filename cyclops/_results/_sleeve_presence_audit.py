"""Audit: is the 'Cyclops + sleeve-presence' finding (WR 80% vs 59%)
confounded by vwap distribution?

If sleeve-active markets just happen to have higher vwap (closer to $1),
then their high WR is mechanical (winning a $0.80 share pays only $0.20)
and offers no real edge.
"""
import json
from pathlib import Path
import pandas as pd
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import CANON
SCALE = 1/25

# Build sleeve-fired slug set
ev = pd.read_parquet(Path(CANON) / "trading_events_30d.parquet")
ev = ev[ev.kind == "poly_updown_resolution"]
btc5 = ev[ev.sleeve_id.str.contains("btc_5m", na=False)]
d = btc5["data"].apply(json.loads)
btc5_df = pd.json_normalize(d)
btc5_df["sleeve_id"] = btc5["sleeve_id"].values
res = pd.read_parquet(Path(CANON) / "resolutions.parquet")
cid2slug = dict(zip(res.market_id, res.slug))
btc5_df["slug"] = btc5_df["condition_id"].map(cid2slug)
sleeve_active_slugs = set(btc5_df.slug.dropna().unique())
print(f"Total slugs with at least one BTC 5m sleeve resolution: {len(sleeve_active_slugs)}")

# Per-sleeve slug coverage
per_sleeve = btc5_df.groupby("sleeve_id")["slug"].nunique().sort_values(ascending=False)
print(f"\nPer-sleeve unique slug count:")
print(per_sleeve.to_string())

# Now check Cyclops S7
cy = pd.read_csv("cyclops/_results/p5_full_depth_p3.csv")
cy_f = cy[cy.fired == True].copy()
cy_f["pnl_1"] = cy_f["pnl_usd"] * SCALE
cy_f["sleeve_active"] = cy_f.slug.isin(sleeve_active_slugs)

print(f"\nCyclops S7 fires: {len(cy_f)}")
print(f"  with sleeve activity: {cy_f.sleeve_active.sum()}")
print(f"  without sleeve activity: {(~cy_f.sleeve_active).sum()}")

print("\n=== Stratified by sleeve_active, w/ vwap breakdown ===")
for active, label in [(True, "sleeve_ACTIVE"), (False, "sleeve_SILENT")]:
    sub = cy_f[cy_f.sleeve_active == active]
    print(f"\n  {label}: n={len(sub)}")
    print(f"    WR={sub.won.mean():.3f}  mean_vwap=${sub.vwap_entry.mean():.4f}  "
          f"breakeven_WR_at_vwap={sub.vwap_entry.mean():.3f}")
    print(f"    edge_vs_breakeven={(sub.won.mean() - sub.vwap_entry.mean())*100:+.2f}pp")
    print(f"    mean_pnl_1=${sub.pnl_1.mean():+.4f}  total=${sub.pnl_1.sum():+.2f}")
    # Vwap bucket breakdown
    bins = [0.3, 0.4, 0.5, 0.6, 0.7, 1.01]
    sub2 = sub.copy()
    sub2["vwap_bin"] = pd.cut(sub2.vwap_entry, bins=bins)
    bb = sub2.groupby("vwap_bin", observed=True).agg(
        n=("pnl_1", "size"),
        wr=("won", "mean"),
        mean_vwap=("vwap_entry", "mean"),
        mean_pnl=("pnl_1", "mean"),
        edge_pp=("won", lambda x: 0),  # placeholder
    )
    bb["edge_pp"] = (bb["wr"] - bb["mean_vwap"]) * 100
    print(f"    vwap bucket breakdown:")
    print(bb.to_string())

# Per-sleeve agreement on Cyclops slugs (no double counting)
print("\n=== Per-sleeve WR-lift on Cyclops S7 slugs ===")
cy_slugs = set(cy_f.slug)
for sl in per_sleeve.index:
    sl_slugs = set(btc5_df[btc5_df.sleeve_id == sl].slug.dropna())
    overlap = cy_slugs & sl_slugs
    if len(overlap) < 3:
        continue
    sub = cy_f[cy_f.slug.isin(overlap)]
    if sub.empty:
        continue
    print(f"  {sl:<40s}  cy_overlap={len(overlap):3d}  WR={sub.won.mean():.3f}  "
          f"mean_pnl=${sub.pnl_1.mean():+.4f}  total=${sub.pnl_1.sum():+.2f}")
