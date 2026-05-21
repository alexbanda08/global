"""Slug-dense V2 simulator — fire on ALL opportunities for selected slugs.

The V2 sample (2000 random fires, 1.6 fires/slug) under-represents the
wallet regime (30-170 fires/slug). This simulator picks N slugs that have
the most opportunities and fires on EVERY tick where conditions hold,
giving a realistic per-slug PnL distribution.

Output: per-slug PnL with class (PURE_ONLY / ONE_SIDE_PARTIAL / BOTH_SIDES_PARTIALS).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions  # noqa: E402
from fees import poly_maker_rebate_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS  # noqa: E402

from fill_detector_tradetape import (  # noqa: E402
    load_trades_for_asset, index_trades_by_key, detect_fill, estimate_queue_ahead,
)

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
NOTIONAL = 2.5


def per_fire_pnl(ask_up, ask_dn, fill_up, fill_dn, outcome, notional):
    n = notional
    mint_cost = n * 1.0
    reb_u = n * poly_maker_rebate_per_share(ask_up, FEE_RATE) if fill_up else 0.0
    reb_d = n * poly_maker_rebate_per_share(ask_dn, FEE_RATE) if fill_dn else 0.0
    cash = (n * ask_up if fill_up else 0.0) + (n * ask_dn if fill_dn else 0.0)
    if fill_up and fill_dn:
        return cash + reb_u + reb_d - mint_cost
    if not fill_up and not fill_dn:
        return 0.0
    held = "Down" if fill_up else "Up"
    won = (outcome == held)
    return cash + reb_u + reb_d + (n if won else 0.0) - mint_cost


def simulate_slug(
    slug: str, outcome: str, ops_slug: pd.DataFrame, tidx_up, tidx_dn,
    notional: float, detector: str = "opt",
):
    """Simulate firing on EVERY opportunity for one slug. Returns per-fire PnLs."""
    fires = []
    for r in ops_slug.itertuples(index=False):
        our_shares_up = notional / max(r.ask_up, 0.001)
        our_shares_dn = notional / max(r.ask_dn, 0.001)
        q_up = estimate_queue_ahead(r.size_up)
        q_dn = estimate_queue_ahead(r.size_dn)
        fu = detect_fill(tidx_up, r.ask_up, int(r.ts), our_shares_up, q_up)
        fd = detect_fill(tidx_dn, r.ask_dn, int(r.ts), our_shares_dn, q_dn)
        if detector == "opt":
            fup = fu.optimistic_filled; fdn = fd.optimistic_filled
        elif detector == "q":
            fup = fu.queue_aware_filled; fdn = fd.queue_aware_filled
        else:
            raise ValueError(detector)
        pnl = per_fire_pnl(r.ask_up, r.ask_dn, fup, fdn, outcome, notional)
        fires.append({
            "ts": int(r.ts), "ask_up": r.ask_up, "ask_dn": r.ask_dn,
            "fill_up": fup, "fill_dn": fdn, "pnl": pnl,
            "scenario": "BOTH" if (fup and fdn)
                        else ("NEITHER" if not (fup or fdn)
                              else ("Down_HELD" if fup else "Up_HELD")),
        })
    return pd.DataFrame(fires)


def run_cell(cell: str, n_slugs: int = 50, notional: float = NOTIONAL, detector: str = "opt"):
    asset = cell.split("_")[0]
    R = ROOT / "data" / "v4" / "canonical" / "_results"
    op = pd.read_parquet(R / f"mint_and_sell_v2_{cell}_2026_05_16" / "opportunities.parquet")
    res = load_resolutions(assets=[asset.upper()], timeframes=[cell.split("_")[1]])[["slug","outcome"]].drop_duplicates(subset="slug")
    op = op.merge(res, on="slug", how="inner")

    # Filter to slugs with trade coverage
    tr_path = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset.lower()}.parquet"
    tr_slugs = set(pd.read_parquet(tr_path, columns=["slug"])["slug"].unique())
    op = op[op.slug.isin(tr_slugs)].reset_index(drop=True)

    # Pick top-N slugs by opportunity count
    counts = op.groupby("slug").size().sort_values(ascending=False)
    picked = counts.head(n_slugs).index.tolist()
    op_dense = op[op.slug.isin(picked)].reset_index(drop=True)
    print(f"[{cell}] {len(picked)} slugs, {len(op_dense):,} opportunities, "
          f"{len(op_dense)/len(picked):.0f} ops/slug avg", flush=True)

    # Load trades, index
    trades = load_trades_for_asset(asset)
    trades = trades[trades.slug.isin(picked)].reset_index(drop=True)
    tidx = index_trades_by_key(trades)
    del trades
    print(f"[{cell}] indexed {len(tidx)} (slug, outcome) keys", flush=True)

    all_fires = []
    slug_rows = []
    for slug in picked:
        sub = op_dense[op_dense.slug == slug].sort_values("ts").reset_index(drop=True)
        outcome = sub.outcome.iloc[0]
        tup = tidx.get((slug, "Up"))
        tdn = tidx.get((slug, "Down"))
        df_fires = simulate_slug(slug, outcome, sub, tup, tdn, notional, detector)
        df_fires["slug"] = slug
        all_fires.append(df_fires)

        n_up_held = (df_fires.scenario == "Up_HELD").sum()
        n_dn_held = (df_fires.scenario == "Down_HELD").sum()
        if n_up_held > 0 and n_dn_held > 0:
            cls = "BOTH_SIDES_PARTIALS"
        elif n_up_held == 0 and n_dn_held == 0:
            cls = "PURE_ONLY"
        else:
            cls = "ONE_SIDE_PARTIAL"
        slug_rows.append({
            "slug": slug, "outcome": outcome,
            "n_fires": len(df_fires),
            "n_both": (df_fires.scenario == "BOTH").sum(),
            "n_up_held": n_up_held, "n_dn_held": n_dn_held,
            "n_neither": (df_fires.scenario == "NEITHER").sum(),
            "slug_pnl": df_fires.pnl.sum(),
            "class": cls,
        })

    sg = pd.DataFrame(slug_rows)
    cls_view = sg.groupby("class").agg(
        n_slugs=("slug", "count"),
        mean_fires_per_slug=("n_fires", "mean"),
        mean_pnl=("slug_pnl", "mean"),
        median_pnl=("slug_pnl", "median"),
        total_pnl=("slug_pnl", "sum"),
    ).reset_index()

    print(f"\n=== {cell} dense simulation (n_slugs={len(picked)}, detector={detector}, notional=${notional}) ===")
    print(cls_view.to_string(index=False))

    sum_pnl = sg.slug_pnl.sum()
    total_fires = sg.n_fires.sum()
    print(f"\n  Sum slug PnL: ${sum_pnl:+.2f}")
    print(f"  Avg slug PnL: ${sg.slug_pnl.mean():+.4f}")
    print(f"  Avg fires/slug: {sg.n_fires.mean():.0f}")
    print(f"  Per-fire mean: ${sum_pnl/total_fires:+.4f}")

    # Extrapolation: how many distinct slugs in 21d window for this cell?
    n_slugs_window = res.slug.nunique()
    if n_slugs_window > len(picked):
        # Assume average across the sampled slugs is representative
        proj = sg.slug_pnl.mean() * n_slugs_window
        print(f"\n  Projection (assuming {n_slugs_window:,} slugs/21d, same density):")
        print(f"    $/21d: ${proj:+,.2f}")
        print(f"    $/day: ${proj/21:+,.2f}")

    out_dir = R / f"mint_and_sell_v3_slug_dense_{cell}_2026_05_16"
    out_dir.mkdir(exist_ok=True)
    sg.to_parquet(out_dir / "slug_pnl.parquet", index=False)
    pd.concat(all_fires).to_parquet(out_dir / "fires.parquet", index=False)
    print(f"\n  → wrote {out_dir}")
    return sg


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="sol_15m")
    ap.add_argument("--n-slugs", type=int, default=50)
    ap.add_argument("--notional", type=float, default=2.5)
    ap.add_argument("--detector", default="opt", choices=("opt", "q"))
    args = ap.parse_args()
    run_cell(args.cell, args.n_slugs, args.notional, args.detector)
