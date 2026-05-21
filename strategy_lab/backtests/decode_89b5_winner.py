"""
Deep decode of 0x89b5cdaa — the BIGGEST per-slug winner ($248/slug, 100% maker, 100% SELL).

What makes them so profitable?
  - 100% maker (post asks, get filled)
  - 100% SELL (mint pairs, sell back)
  - 41% paired (mostly single-outcome focus)
  - Pattern: minted pairs, sold ONLY one side, redeemed the leftover other side

Per-slug behavior:
  - What outcomes do they sell? (Up only, Down only, or both?)
  - Slug selection: do they bias toward the winning side?
  - Size + price discipline
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions

WCACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0x89b5cdaa"


def main():
    fills = pd.read_parquet(WCACHE / "fills.parquet")
    print(f"Total fills: {len(fills)}")
    print(f"  unique slugs: {fills['slug'].nunique()}")

    btc = fills[fills["asset_sym"] == "BTC"]
    print(f"  BTC fills: {len(btc)}")
    eth = fills[fills["asset_sym"] == "ETH"]
    print(f"  ETH fills: {len(eth)}")
    sol = fills[fills["asset_sym"] == "SOL"]
    print(f"  SOL fills: {len(sol)}")

    # Side analysis per outcome
    print("\n--- Side distribution per outcome ---")
    pivot = fills.groupby(["outcome", "side"]).size().unstack(fill_value=0)
    print(pivot)
    # Maker pct
    print(f"\n--- Maker% ---")
    print(f"  overall: {fills['is_maker'].mean()*100:.1f}%")

    # Get outcomes
    res = load_resolutions(assets=["BTC", "ETH", "SOL"])
    slug_outcome = dict(zip(res["slug"], res["outcome"]))
    fills["outcome_truth"] = fills["slug"].map(slug_outcome)

    # Per-slug: which outcome did they trade?
    print("\n--- Slug-level breakdown (which side did they SELL?) ---")
    per_slug = fills.groupby("slug").agg(
        outcomes_traded=("outcome", lambda s: sorted(s.unique().tolist())),
        side_traded=("outcome", lambda s: s.unique().tolist() if len(s.unique()) == 1 else "BOTH"),
    ).reset_index()
    per_slug["outcomes_str"] = per_slug["outcomes_traded"].apply(lambda x: ",".join(x))
    print(per_slug["outcomes_str"].value_counts())

    # Did they sell the WINNER or LOSER side most of the time?
    print("\n--- Did they sell winning or losing side? ---")
    fills_with_truth = fills.merge(per_slug[["slug", "outcomes_str"]], on="slug")
    fills_with_truth["sold_winner"] = fills_with_truth["outcome"] == fills_with_truth["outcome_truth"]
    print(f"  Sold WINNING side: {fills_with_truth['sold_winner'].mean()*100:.1f}%")
    print(f"  Sold LOSING side:  {(1 - fills_with_truth['sold_winner']).mean()*100:.1f}%")

    # Per side they engage on (Up vs Down) — winning probability
    print("\n--- When they engage ONE side, was it the winner? ---")
    single_side = per_slug[per_slug["outcomes_str"].isin(["Up", "Down"])].copy()
    single_side["outcome_truth"] = single_side["slug"].map(slug_outcome)
    single_side["picked_winner"] = single_side["outcomes_str"] == single_side["outcome_truth"]
    print(f"  Single-side slugs: {len(single_side)}")
    print(f"  Picked winning side: {single_side['picked_winner'].mean()*100:.1f}%")
    print()
    print("  Side breakdown:")
    print(f"  Only Up traded:   {(single_side['outcomes_str'] == 'Up').sum()} slugs, "
          f"winners = {(single_side[single_side['outcomes_str'] == 'Up']['outcome_truth'] == 'Up').sum()} "
          f"= {(single_side[single_side['outcomes_str'] == 'Up']['outcome_truth'] == 'Up').mean()*100:.1f}%")
    print(f"  Only Down traded: {(single_side['outcomes_str'] == 'Down').sum()} slugs, "
          f"winners = {(single_side[single_side['outcomes_str'] == 'Down']['outcome_truth'] == 'Down').sum()} "
          f"= {(single_side[single_side['outcomes_str'] == 'Down']['outcome_truth'] == 'Down').mean()*100:.1f}%")

    # When BOTH sides traded - did they bias toward winner?
    both = per_slug[per_slug["outcomes_str"] == "Down,Up"].copy()
    both["outcome_truth"] = both["slug"].map(slug_outcome)
    print(f"\n  BOTH sides traded: {len(both)} slugs")
    if len(both) > 0:
        # Compute share of fills on winner vs loser
        sub = fills.merge(both[["slug"]], on="slug")
        size_by_side = sub.groupby(["slug", "outcome"]).agg(total_size=("size", "sum")).reset_index()
        pivot_sz = size_by_side.pivot(index="slug", columns="outcome", values="total_size").fillna(0)
        pivot_sz["truth"] = pivot_sz.index.map(slug_outcome)
        # Pct of size on winner
        pivot_sz["winner_size"] = pivot_sz.apply(
            lambda r: r["Up"] if r["truth"] == "Up" else r["Down"], axis=1
        )
        pivot_sz["loser_size"] = pivot_sz.apply(
            lambda r: r["Down"] if r["truth"] == "Up" else r["Up"], axis=1
        )
        pivot_sz["winner_pct"] = pivot_sz["winner_size"] / (pivot_sz["winner_size"] + pivot_sz["loser_size"]) * 100
        print(f"  Median size% on winner: {pivot_sz['winner_pct'].median():.1f}%")
        print(f"  Mean size% on winner:   {pivot_sz['winner_pct'].mean():.1f}%")
        print(f"  P25 winner%: {pivot_sz['winner_pct'].quantile(0.25):.1f}%")
        print(f"  P75 winner%: {pivot_sz['winner_pct'].quantile(0.75):.1f}%")

    # Asset breakdown
    print("\n--- Asset breakdown (where they make money) ---")
    by_asset = fills.groupby("asset_sym").agg(
        n_slugs=("slug", "nunique"),
        n_fills=("size", "count"),
        total_size=("size", "sum"),
        total_usd=("usd", "sum"),
    ).reset_index()
    print(by_asset.to_string(index=False))

    # TF breakdown
    print("\n--- TF breakdown ---")
    by_tf = fills.groupby("mc").agg(
        n_slugs=("slug", "nunique"),
        n_fills=("size", "count"),
        median_size=("size", "median"),
        median_offset=("offset_from_slot_start_s", "median"),
    ).reset_index()
    print(by_tf.to_string(index=False))


if __name__ == "__main__":
    main()
