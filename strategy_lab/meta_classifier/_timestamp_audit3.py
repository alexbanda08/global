"""Decompose G6 'lead-lag' alpha — is it real, or a vol/noise confound?

Tests:
  X1. Pure volatility filter — fire when |bin_ret_2m| is in BOTTOM decile (low-vol regime).
       If this matches G6 hit rate, the "lead-lag" claim is bogus.

  X2. Real-lead filter — fire when |bin_ret_2m - coin_ret_2m| > 5 bp (forces meaningful gap).
       Should be near-empty given audit2 showed gaps of <1 bp typical.

  X3. G6 cell-by-cell — split G6 fires by |bin_ret_2m| magnitude bucket. If
       G6's hit rate is concentrated in tiny-move bucket, it's a vol filter.

  X4. Direct correlation: |bin_ret_2m| vs P(G6 fires).  If G6 is essentially the
       low-vol slice, the correlation will be strong negative.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

# Load the per-trade output from G6 run
LEAD_DIR = ROOT / "data" / "v4" / "refresh_2026_05_09" / "coinbase_lead"


def main():
    print("=== G6 ALPHA DECOMPOSITION ===\n")

    p = LEAD_DIR / "per_trade.csv"
    df = pd.read_csv(p)
    print(f"loaded {len(df)} per-trade rows from {p}")

    # Restrict to HOLD policy + G6 + B0 (we want to compare on identical data)
    hold = df[df.policy == "HOLD"].copy()
    b0 = hold[hold.variant == "B0"].copy()
    g6 = hold[hold.variant == "G6"].copy()

    # ------------------------------------------------------------------
    # X1: pure volatility filter on B0 — does selecting LOW |ret_2m| match G6?
    # ------------------------------------------------------------------
    print(f"\n[X1] Pure volatility filter — apply on B0, compare to G6.")
    b0["abs_ret"] = b0.ret_2m.abs()
    print(f"    B0 baseline (n={len(b0)}): hit={(b0.pnl>0).mean()*100:.2f}%, "
          f"mean_pnl=${b0.pnl.mean():.2f}, total_pnl=${b0.pnl.sum():.2f}")
    print(f"    G6 (n={len(g6)}): hit={(g6.pnl>0).mean()*100:.2f}%, "
          f"mean_pnl=${g6.pnl.mean():.2f}, total_pnl=${g6.pnl.sum():.2f}")
    # Decile split on B0 by |bin_ret_2m|
    print(f"\n    B0 split by |bin_ret_2m| decile:")
    b0["abs_ret_decile"] = pd.qcut(b0.abs_ret, q=10, labels=range(10), duplicates="drop")
    by_decile = b0.groupby("abs_ret_decile", observed=True).agg(
        n=("pnl", "size"),
        abs_ret_min=("abs_ret", "min"),
        abs_ret_max=("abs_ret", "max"),
        hit_pct=("pnl", lambda s: round(100 * (s > 0).mean(), 2)),
        mean_pnl=("pnl", lambda s: round(s.mean(), 4)),
        total_pnl=("pnl", lambda s: round(s.sum(), 2)),
    ).reset_index()
    by_decile["abs_ret_min_bp"] = (by_decile["abs_ret_min"] * 10000).round(2)
    by_decile["abs_ret_max_bp"] = (by_decile["abs_ret_max"] * 10000).round(2)
    print(by_decile[["abs_ret_decile", "n", "abs_ret_min_bp", "abs_ret_max_bp",
                      "hit_pct", "mean_pnl", "total_pnl"]].to_string(index=False))

    # ------------------------------------------------------------------
    # X2: directly check the |bin - coin| GAP distribution on G6 trades
    # ------------------------------------------------------------------
    print(f"\n[X2] |bin_ret - coin_ret| gap distribution on G6 fires:")
    g6["gap_bp"] = (g6.ret_2m - g6.coin_ret_2m).abs() * 10000
    print(f"    median gap: {g6.gap_bp.median():.2f} bp")
    print(f"    p25:        {g6.gap_bp.quantile(0.25):.2f} bp")
    print(f"    p75:        {g6.gap_bp.quantile(0.75):.2f} bp")
    print(f"    p95:        {g6.gap_bp.quantile(0.95):.2f} bp")
    print(f"    p99:        {g6.gap_bp.quantile(0.99):.2f} bp")
    print(f"    max:        {g6.gap_bp.max():.2f} bp")
    print(f"    -> If median gap < 2 bp, the 'lead' is sub-noise.")

    # ------------------------------------------------------------------
    # X3: split G6 by ABSOLUTE bin_ret magnitude bucket. If hit rate is
    #     concentrated in tiny-move bucket, it's a vol filter.
    # ------------------------------------------------------------------
    print(f"\n[X3] G6 split by |bin_ret_2m| magnitude bucket:")
    g6["abs_ret_bp"] = g6.ret_2m.abs() * 10000
    bins = [0, 5, 10, 20, 50, 100, 1000]
    g6["abs_ret_bucket"] = pd.cut(g6.abs_ret_bp, bins=bins, labels=[
        "<5bp", "5-10", "10-20", "20-50", "50-100", ">100"
    ], include_lowest=True)
    by_bucket = g6.groupby("abs_ret_bucket", observed=True).agg(
        n=("pnl", "size"),
        hit_pct=("pnl", lambda s: round(100 * (s > 0).mean(), 2)),
        mean_pnl=("pnl", lambda s: round(s.mean(), 4)),
        total_pnl=("pnl", lambda s: round(s.sum(), 2)),
    ).reset_index()
    print(by_bucket.to_string(index=False))

    # ------------------------------------------------------------------
    # X4: same split for B0 — for visual comparison
    # ------------------------------------------------------------------
    print(f"\n[X4] B0 baseline split by |bin_ret_2m| magnitude bucket:")
    b0["abs_ret_bp"] = b0.ret_2m.abs() * 10000
    b0["abs_ret_bucket"] = pd.cut(b0.abs_ret_bp, bins=bins, labels=[
        "<5bp", "5-10", "10-20", "20-50", "50-100", ">100"
    ], include_lowest=True)
    by_bucket_b0 = b0.groupby("abs_ret_bucket", observed=True).agg(
        n=("pnl", "size"),
        hit_pct=("pnl", lambda s: round(100 * (s > 0).mean(), 2)),
        mean_pnl=("pnl", lambda s: round(s.mean(), 4)),
        total_pnl=("pnl", lambda s: round(s.sum(), 2)),
    ).reset_index()
    print(by_bucket_b0.to_string(index=False))

    # ------------------------------------------------------------------
    # X5: side-by-side comparison — for the SAME magnitude bucket, does G6 hit > B0 hit?
    # ------------------------------------------------------------------
    print(f"\n[X5] G6 hit RATE vs B0 hit RATE within same |bin_ret_2m| bucket:")
    cmp = by_bucket.merge(by_bucket_b0, on="abs_ret_bucket", how="outer",
                            suffixes=("_g6", "_b0"))
    cmp["hit_lift_pp"] = (cmp.hit_pct_g6 - cmp.hit_pct_b0).round(2)
    cmp["mean_lift"] = (cmp.mean_pnl_g6 - cmp.mean_pnl_b0).round(4)
    print(cmp[["abs_ret_bucket", "n_b0", "n_g6", "hit_pct_b0", "hit_pct_g6",
                "hit_lift_pp", "mean_pnl_b0", "mean_pnl_g6", "mean_lift"]].to_string(index=False))
    print("\n    -> If hit_lift_pp is ~0 across buckets, G6 is a magnitude/vol filter,")
    print("       NOT genuine lead-lag alpha. The apparent lift is from selecting low-vol bucket.")
    print("    -> If hit_lift_pp is meaningfully positive INSIDE each bucket, lead-lag IS real")
    print("       (G6 picks better markets even after controlling for move magnitude).")


if __name__ == "__main__":
    main()
