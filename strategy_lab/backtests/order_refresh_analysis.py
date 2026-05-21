"""
Order refresh analysis — how often do wallets post new orders vs fill existing?

Each fill row has order_hash. Group by (slug, order_hash, side) to see:
  - n_fills_per_order: how many partial fills before order completes
  - n_distinct_orders_per_slug: how many unique posts per slug
  - avg_order_size: total filled size per order

This tells us if the wallet REFRESHES orders frequently or LET them sit.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WALLET_CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
OUT_DIR = ROOT / "strategy_lab" / "backtests"

WALLETS = ["0x04b6d7e9", "0xeebde7a0", "0x89b5cdaa", "0xcfb103c3", "0xce25e214"]


for w in WALLETS:
    p = WALLET_CACHE / w / "fills.parquet"
    if not p.exists():
        print(f"{w}: no fills.parquet")
        continue

    df = pd.read_parquet(p)
    df = df[df["mc"].isin(["updown_5m", "updown_15m"])]
    df = df[df["asset_sym"] == "BTC"]
    if df.empty:
        print(f"{w}: no BTC updown fills")
        continue

    # Filter to maker fills only (their posted orders)
    maker = df[df["is_maker"] == True].copy()
    if maker.empty:
        print(f"{w}: no maker fills (likely taker-dominant)")
        # taker stats
        taker = df[df["is_maker"] == False].copy()
        print(f"  taker stats: {len(taker)} fills across {taker['slug'].nunique()} slugs")
        taker_per_slug = taker.groupby("slug").size()
        print(f"  taker fills/slug: median={taker_per_slug.median():.0f} p90={taker_per_slug.quantile(0.9):.0f}")
        continue

    print(f"\n=== {w}  maker fills: {len(maker)}")

    # We need order_hash — fills.parquet may not have it. Let me check.
    if "order_hash" not in maker.columns:
        # Fall back: count by (slug, side, time-bucket) — proxy for unique posts
        # Each refresh is a new "order" if posted >20s after previous
        maker_sorted = maker.sort_values(["slug", "outcome", "ts_s"])
        maker_sorted["dt_prev"] = maker_sorted.groupby(["slug", "outcome"])["ts_s"].diff()
        maker_sorted["new_order"] = (maker_sorted["dt_prev"].isna() |
                                       (maker_sorted["dt_prev"] > 5))
        maker_sorted["order_idx"] = maker_sorted.groupby(["slug", "outcome"])["new_order"].cumsum()

        per_order = maker_sorted.groupby(["slug", "outcome", "order_idx"]).agg(
            n_fills=("ts_s", "count"),
            total_size=("size", "sum"),
            first_ts=("ts_s", "min"),
            last_ts=("ts_s", "max"),
            avg_px=("price", "mean"),
            offset_first=("offset_from_slot_start_s", "min"),
        ).reset_index()

        per_slug_orders = per_order.groupby(["slug", "outcome"]).agg(
            n_orders=("order_idx", "count"),
            avg_fills_per_order=("n_fills", "mean"),
            avg_order_size=("total_size", "mean"),
        ).reset_index()

        print(f"  Heuristic: distinct 'orders' inferred from >5s gaps")
        print(f"  Per slug per outcome: orders med={per_slug_orders['n_orders'].median():.0f} "
              f"p90={per_slug_orders['n_orders'].quantile(0.9):.0f}")
        print(f"  Fills per order: med={per_slug_orders['avg_fills_per_order'].median():.1f} "
              f"p90={per_slug_orders['avg_fills_per_order'].quantile(0.9):.1f}")
        print(f"  Order size (filled): med={per_slug_orders['avg_order_size'].median():.1f} shares "
              f"p90={per_slug_orders['avg_order_size'].quantile(0.9):.1f} shares")
        # Distribution of offset_from_slot_start
        bins = [-100, 0, 30, 60, 120, 180, 240, 300, 600, 900]
        offsets = maker_sorted["offset_from_slot_start_s"].dropna()
        hist = pd.cut(offsets, bins=bins).value_counts(normalize=True).sort_index() * 100
        print(f"  Offset_from_slot_start distribution (% of fills):")
        for k, v in hist.items():
            print(f"    {str(k):20s}  {v:5.1f}%")
        # Size distribution
        sz_quant = maker["size"].quantile([0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
        print(f"  Maker fill SIZE quantiles: " +
              " ".join(f"p{int(k*100)}={v:.1f}" for k, v in sz_quant.items()))
        # Price distribution
        px_quant = maker["price"].quantile([0.10, 0.25, 0.50, 0.75, 0.90])
        print(f"  Maker fill PRICE quantiles: " +
              " ".join(f"p{int(k*100)}={v:.3f}" for k, v in px_quant.items()))
