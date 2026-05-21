"""Compute PnL for fills detected by trade-tape detector and compare to v2 baseline.

Reads `mint_and_sell_v3_tradetape_<cell>_2026_05_16/fill_compare.parquet`
(produced by fill_detector_tradetape.py) plus the v2
`policy_compare.parquet`, computes PnL under three scenarios:
  - v2_bid:    pnl_hold from v2 (existing baseline)
  - v3_opt:    pnl assuming optimistic taker-print fills
  - v3_q:      pnl assuming queue-aware fills

Then aggregates at slug level (the regime wallets operate in) and
extrapolates $/day for the full opportunity universe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

from fees import (  # noqa: E402
    poly_maker_rebate_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS,
)

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
NOTIONAL = 2.5
WINDOW_DAYS = 21.0


def pnl_for_scenario(row, fill_up: bool, fill_dn: bool, notional: float) -> float:
    """Compute pnl_hold for a single fire under given fill outcomes.

    Fee/rebate math from partial_fill_policy_compare_v2.py:evaluate_opportunity.
    """
    n = notional
    au = float(row["ask_up"]); ad = float(row["ask_dn"])
    mint_cost = n * 1.0

    reb_u = n * poly_maker_rebate_per_share(au, FEE_RATE) if fill_up else 0.0
    reb_d = n * poly_maker_rebate_per_share(ad, FEE_RATE) if fill_dn else 0.0
    cash_from_filled = (n * au if fill_up else 0.0) + (n * ad if fill_dn else 0.0)

    if fill_up and fill_dn:
        return cash_from_filled + reb_u + reb_d - mint_cost
    if not fill_up and not fill_dn:
        return 0.0  # cost-free if we mergePositions() recovers full $N

    held_side = "Down" if fill_up else "Up"
    held_won = (row["outcome"] == held_side)
    held_redeem = n * (1.0 if held_won else 0.0)
    return cash_from_filled + reb_u + reb_d + held_redeem - mint_cost


def analyze_cell(cell: str, n_universe: int) -> dict:
    R = ROOT / "data" / "v4" / "canonical" / "_results"
    fc_path = R / f"mint_and_sell_v3_tradetape_{cell}_2026_05_16" / "fill_compare.parquet"
    pc_path = R / f"mint_and_sell_v2_{cell}_2026_05_16" / "policy_compare.parquet"
    if not fc_path.exists() or not pc_path.exists():
        return None

    fc = pd.read_parquet(fc_path)
    pc = pd.read_parquet(pc_path)[["slug", "ts", "pnl_hold"]].rename(columns={"pnl_hold": "pnl_v2_bid"})
    df = fc.merge(pc, on=["slug", "ts"], how="left")

    df["pnl_v3_opt"] = df.apply(lambda r: pnl_for_scenario(r, r.fill_up_opt, r.fill_dn_opt, NOTIONAL), axis=1)
    df["pnl_v3_q"] = df.apply(lambda r: pnl_for_scenario(r, r.fill_up_q, r.fill_dn_q, NOTIONAL), axis=1)

    n = len(df)
    n_slugs = df.slug.nunique()
    fires_per_slug = n / max(n_slugs, 1)

    sample_per_fire = {
        "v2_bid": df.pnl_v2_bid.mean(),
        "v3_opt": df.pnl_v3_opt.mean(),
        "v3_q":   df.pnl_v3_q.mean(),
    }
    sample_total = {k: df[f"pnl_{k}"].sum() for k in sample_per_fire}

    # Extrapolate per-fire $/day = sample_mean * n_universe / window_days
    perday_per_fire = {k: v * n_universe / WINDOW_DAYS for k, v in sample_per_fire.items()}

    # Slug-level aggregation
    def classify(s):
        n_up_held = (s.scenario_opt == "Up_HELD").sum()  # Down filled, Up held
        n_dn_held = (s.scenario_opt == "Down_HELD").sum()  # Up filled, Down held
        if n_up_held > 0 and n_dn_held > 0:
            return "BOTH_SIDES_PARTIALS"
        if n_up_held == 0 and n_dn_held == 0:
            return "PURE_ONLY"
        return "ONE_SIDE_PARTIAL"

    slug_agg = df.groupby("slug").apply(lambda s: pd.Series({
        "n_fires": len(s),
        "pnl_v2_bid_sum": s.pnl_v2_bid.sum(),
        "pnl_v3_opt_sum": s.pnl_v3_opt.sum(),
        "pnl_v3_q_sum":   s.pnl_v3_q.sum(),
        "class_opt": classify(s),
    }), include_groups=False).reset_index()

    cls_view = slug_agg.groupby("class_opt").agg(
        n_slugs=("slug", "count"),
        mean_v2_bid=("pnl_v2_bid_sum", "mean"),
        mean_v3_opt=("pnl_v3_opt_sum", "mean"),
        mean_v3_q=("pnl_v3_q_sum", "mean"),
        total_v2_bid=("pnl_v2_bid_sum", "sum"),
        total_v3_opt=("pnl_v3_opt_sum", "sum"),
    ).reset_index()

    print(f"\n=== {cell} (n={n} fires, {n_slugs} slugs, {fires_per_slug:.1f} fires/slug, n_universe={n_universe:,}) ===")
    print("Per-fire mean PnL:")
    for k, v in sample_per_fire.items():
        print(f"  {k:8s}: ${v:+.4f}  | extrapolated ${perday_per_fire[k]:+,.0f}/day")
    print()
    print("Slug-level class breakdown (slug-mean PnL):")
    print(cls_view.to_string(index=False))

    return {
        "cell": cell,
        "n_universe": n_universe,
        "fires_per_slug_sample": fires_per_slug,
        **{f"per_fire_{k}": v for k, v in sample_per_fire.items()},
        **{f"perday_{k}": v for k, v in perday_per_fire.items()},
        "slug_class_view": cls_view,
        "df": df,
    }


# Opportunity counts per cell from V2 report
N_UNIVERSE = {
    "btc_5m":  1_835_980,
    "btc_15m": 1_041_121,
    "eth_5m":    986_863,
    "eth_15m":   498_817,
    "sol_5m":    556_856,
    "sol_15m":   293_532,
}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="sol_15m")
    args = ap.parse_args()
    analyze_cell(args.cell, N_UNIVERSE[args.cell])
