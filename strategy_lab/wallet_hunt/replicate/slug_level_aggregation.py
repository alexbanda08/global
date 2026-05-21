"""Aggregate per-fire PnL at the SLUG level.

Hypothesis: at the per-fire level, partials look catastrophic because
held_WR is selection-biased (the side that filled is the likely winner →
we hold the unlikely side, hits only 17-30% of the time).

But if a wallet fires MANY times on the same slug, partials of BOTH sides
occur:
  - Up-only fires (Down held) — we accumulate Down tokens
  - Down-only fires (Up held) — we accumulate Up tokens
Whichever side ultimately wins, ONE of those token piles redeems at $1
each. The "selection bias" at the per-fire level washes out at the slug
level because we end up holding both sides.

Test: aggregate `policy_compare.parquet` PnL by slug.
  - slug_pnl_hold = sum of pnl_hold over all fires on that slug
  - slug-mean PnL should be closer to 0 (or positive) than per-fire mean
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

def analyze_cell(cell: str) -> dict:
    p = ROOT / "data" / "v4" / "canonical" / "_results" / f"mint_and_sell_v2_{cell}_2026_05_16" / "policy_compare.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    n_fires = len(df)

    # Per-fire stats
    mean_pf = df.pnl_hold.mean()
    total_pf = df.pnl_hold.sum()

    # Per-slug aggregation
    slug_pnl = df.groupby("slug").agg(
        n_fires=("pnl_hold", "size"),
        slug_pnl=("pnl_hold", "sum"),
        n_both=("scenario", lambda s: (s == "BOTH").sum()),
        n_up_held=("scenario", lambda s: (s == "Down_HELD").sum()),  # Up filled, Down held
        n_dn_held=("scenario", lambda s: (s == "Up_HELD").sum()),    # Down filled, Up held
        n_neither=("scenario", lambda s: (s == "NEITHER").sum()),
    ).reset_index()

    # Slugs with "balanced" partials (within 30% of each other)
    slug_pnl["balance_ratio"] = (
        np.minimum(slug_pnl.n_up_held, slug_pnl.n_dn_held) /
        np.maximum(slug_pnl.n_up_held, slug_pnl.n_dn_held).replace(0, np.nan)
    )

    out = dict(
        cell=cell, n_fires=n_fires, n_slugs=len(slug_pnl),
        fires_per_slug_avg=n_fires / max(len(slug_pnl), 1),
        per_fire_mean=float(mean_pf), per_fire_total=float(total_pf),
        slug_mean=float(slug_pnl.slug_pnl.mean()),
        slug_median=float(slug_pnl.slug_pnl.median()),
        n_pos_slugs=int((slug_pnl.slug_pnl > 0).sum()),
        n_neg_slugs=int((slug_pnl.slug_pnl < 0).sum()),
        pct_pos_slugs=float((slug_pnl.slug_pnl > 0).mean() * 100),
    )

    # Decompose by slug class
    only_pure = slug_pnl[(slug_pnl.n_up_held == 0) & (slug_pnl.n_dn_held == 0)]
    only_one_side_partial = slug_pnl[
        ((slug_pnl.n_up_held > 0) & (slug_pnl.n_dn_held == 0)) |
        ((slug_pnl.n_up_held == 0) & (slug_pnl.n_dn_held > 0))
    ]
    both_side_partials = slug_pnl[(slug_pnl.n_up_held > 0) & (slug_pnl.n_dn_held > 0)]

    out["n_slugs_pure_only"] = len(only_pure)
    out["n_slugs_one_side_partial"] = len(only_one_side_partial)
    out["n_slugs_both_side_partials"] = len(both_side_partials)
    out["pnl_pure_only_slugs"] = float(only_pure.slug_pnl.sum()) if len(only_pure) else 0
    out["pnl_one_side_partial_slugs"] = float(only_one_side_partial.slug_pnl.sum()) if len(only_one_side_partial) else 0
    out["pnl_both_side_partials_slugs"] = float(both_side_partials.slug_pnl.sum()) if len(both_side_partials) else 0
    out["mean_pnl_both_side_partials"] = float(both_side_partials.slug_pnl.mean()) if len(both_side_partials) else float("nan")
    out["mean_pnl_one_side_partial"] = float(only_one_side_partial.slug_pnl.mean()) if len(only_one_side_partial) else float("nan")

    return out


def main():
    cells = ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"]
    rows = [analyze_cell(c) for c in cells]
    rows = [r for r in rows if r]

    print(f"\n=== Per-fire vs slug-level aggregation at $2.5 notional ===\n")
    print(f"{'Cell':<10} {'fires':>8} {'slugs':>6} {'fires/slug':>11} {'per_fire_mean':>15} {'slug_mean':>10} {'%pos_slugs':>11}")
    for r in rows:
        print(f"{r['cell']:<10} {r['n_fires']:>8,} {r['n_slugs']:>6,} {r['fires_per_slug_avg']:>11.1f} "
              f"${r['per_fire_mean']:>13.5f} ${r['slug_mean']:>8.3f} {r['pct_pos_slugs']:>10.1f}%")

    print(f"\n=== Slug class breakdown ===\n")
    print(f"{'Cell':<10} {'pure_only':>12} {'one_side':>15} {'both_sides_partials':>22}")
    print(f"{'':10} {'n / total $':>12} {'n / total $':>15} {'n / total $ / mean$':>22}")
    for r in rows:
        print(f"{r['cell']:<10} {r['n_slugs_pure_only']:>4} ${r['pnl_pure_only_slugs']:>6.2f}   "
              f"{r['n_slugs_one_side_partial']:>4} ${r['pnl_one_side_partial_slugs']:>8.2f}   "
              f"{r['n_slugs_both_side_partials']:>4} ${r['pnl_both_side_partials_slugs']:>8.2f} (mean=${r['mean_pnl_both_side_partials']:.3f})")

    # Save
    pd.DataFrame(rows).to_csv(ROOT / "data" / "v4" / "canonical" / "_results" / "_slug_level_aggregation.csv", index=False)


if __name__ == "__main__":
    main()
