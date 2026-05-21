"""Decode cancel rules for maker wallets via L25 book inference.

Polymarket CLOB is off-chain matched, so cancels never hit the chain.
We infer cancels by tracking the maker's level-2 (price/level) size in the
L25 orderbook stream.

Pipeline per wallet:
  1. Group trades_chain_enriched by order_hash → get (slug, outcome,
     side, price, first_fill_ts, last_fill_ts, total_filled).
  2. Stream L25 for the relevant assets (BTC primary).
  3. For each order, look at L25 size at the order price-level:
       - before first_fill: order is "live" — verify there's at least
         total_filled+remaining size there
       - after last_fill: track when (slug, outcome) book size at that
         price LEVEL drops by remaining/order_size
  4. Classify each order:
       - FILLED_FULL: total_filled close to size on book at post
       - CANCELLED: book size at that level drops without a matching fill
                    in our trades within Δt
       - EXPIRED: book persists to slug-end (slot_start_s + window_s)
  5. Compute:
       - % cancel / fill / expire
       - Order lifetime distribution (last_fill → cancel)
       - Δprice between post-time best_bid and cancel-time best_bid
         (test H1: cancel-when-displaced threshold)
       - Time between post and cancel (test H2: time-based)
       - Cancel-after-fill rate (test H3)
       - Cancel-near-close rate (test H4)

Output: prints summary to console + writes per-order classification
parquet for further analysis.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_orderbook_l25_streaming  # noqa


def decode_wallet(wallet_short: str, n_sample: int = 300, asset: str = "BTC"):
    print(f"\n{'='*78}\n=== {wallet_short} ===\n{'='*78}")
    cache = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / wallet_short
    # Try enriched first; fall back to building from trades_chain + per_leg_chain
    if (cache / "trades_chain_enriched.parquet").exists():
        df = pd.read_parquet(cache / "trades_chain_enriched.parquet")
        print(f"  using trades_chain_enriched ({len(df):,} rows)")
    else:
        # Build it: join trades_chain to per_leg_chain via asset->condition_id
        trades = pd.read_parquet(cache / "trades_chain.parquet")
        legs = pd.read_parquet(cache / "per_leg_chain.parquet")
        # asset -> (condition_id, outcome, slug, slot_start_s, mkt_asset, market_class)
        # asset_id maps via outcome tokens; use trades.asset == leg asset_id ??
        # Fallback: just keep maker-side wallet rows, no slug
        df = trades[trades.wallet_is_maker].copy()
        print(f"  WARNING: no enriched; using trades_chain maker rows ({len(df):,})")
        df["slug"] = None
        df["outcome"] = None
        df["slot_start_s"] = None
        df["mkt_asset"] = None
        df["price_clean"] = df["price"]
        df["size_clean"] = df["size"]
        df["side_clean"] = df["side"]

    # Filter to maker-side fills only
    df = df[df.wallet_is_maker].copy()
    df = df.dropna(subset=["slug", "price_clean", "size_clean", "outcome"])
    df["price_cents"] = (df["price_clean"] * 100).round().astype(int)
    df["timestamp"] = df["timestamp"].astype("int64")

    # Filter to BTC for L25 inference
    if "mkt_asset" in df.columns:
        df_asset = df[df.mkt_asset.str.upper() == asset]
        print(f"  {asset} maker fills: {len(df_asset):,} / {len(df):,} total")
        df = df_asset

    if df.empty:
        print(f"  no {asset} maker fills - skip")
        return None

    # Group by order_hash to get order-level facts
    grp = df.groupby("order_hash", sort=False).agg(
        slug=("slug", "first"),
        outcome=("outcome", "first"),
        side=("side_clean", "first"),
        price=("price_clean", "first"),
        price_cents=("price_cents", "first"),
        total_filled=("size_clean", "sum"),
        first_fill_ts=("timestamp", "min"),
        last_fill_ts=("timestamp", "max"),
        n_fills=("size_clean", "count"),
        slot_start_s=("slot_start_s", "first"),
    ).reset_index()
    print(f"  unique orders: {len(grp):,}")

    # Add slug-end time (slot_start_s + window_s)
    # window_s = 300 for 5m, 900 for 15m
    if "market_class" in df.columns:
        cls = df.groupby("order_hash")["market_class"].first()
        grp = grp.merge(cls.rename("market_class"), left_on="order_hash", right_index=True, how="left")
        grp["window_s"] = grp.market_class.map({"updown_5m": 300, "updown_15m": 900, "updown_1m": 60}).fillna(300).astype(int)
    else:
        grp["window_s"] = 300
    grp["slot_end_ts"] = grp.slot_start_s.astype("int64") + grp.window_s

    # Sample for L25 lookups — random sample to cover diverse slugs.
    # Seeded for reproducibility.
    if len(grp) > n_sample:
        sample = grp.sample(n=n_sample, random_state=42).copy()
    else:
        sample = grp.copy()
    print(f"  random sample: {len(sample):,} orders")

    # Get unique slugs in sample
    sample_slugs = set(sample.slug.dropna().unique())
    print(f"  unique slugs in sample: {len(sample_slugs):,}")

    # Map outcome to asset_id - we need the BTC orderbook for this slug+outcome
    # But L25 is keyed by (slug, outcome) where outcome is the string "Up"/"Down"
    # Load L25 streaming for asset, filter to sample slugs
    print(f"  loading L25 book ({asset}) for {len(sample_slugs)} slugs...")
    l25 = load_orderbook_l25_streaming(asset.upper(), slugs=sample_slugs, subsample_1hz=True)
    print(f"    loaded {len(l25)} (slug, outcome) book streams")

    # For each order: classify
    results = []
    for _, row in sample.iterrows():
        key = (row.slug, row.outcome)
        order_id = row.order_hash[:14]
        if key not in l25:
            results.append({**row.to_dict(), "classification": "NO_L25"})
            continue
        ts_us, ap, az, bp, bz = l25[key]
        ts_s = ts_us / 1_000_000

        # Side: if wallet is SELL (maker sells token) → maker posts on ASK side
        # if wallet is BUY (maker buys token) → maker posts on BID side
        is_ask = row.side == "SELL"
        prices = ap if is_ask else bp
        sizes = az if is_ask else bz

        post_price = float(row.price)
        last_fill_s = float(row.last_fill_ts)
        first_fill_s = float(row.first_fill_ts)
        slot_end_s = float(row.slot_end_ts)

        # Find timestamps after last_fill
        after_idx = np.searchsorted(ts_s, last_fill_s, side="right")
        if after_idx >= len(ts_s):
            results.append({**row.to_dict(), "classification": "NO_BOOK_AFTER", "lifetime_after_last_fill_s": np.nan})
            continue

        # For each book snapshot AFTER last_fill, check size at post_price level
        # If size at that price drops to ~0 → CANCELLED at that snap_ts
        # If size persists until slot_end_s → EXPIRED
        # We allow a price tolerance of ±0.5¢ to handle rounding
        target_cents = int(round(post_price * 100))

        cancelled_ts = None
        # Get level size IMMEDIATELY BEFORE first_fill (= what was posted)
        # then track AFTER last_fill: did the level drop by *more* than
        # what we still owe? If yes → there was a cancel.
        first_idx = max(0, np.searchsorted(ts_s, first_fill_s, side="left") - 1)

        def safe_cents(arr):
            a = np.asarray(arr, dtype=np.float64)
            a = np.where(np.isfinite(a), a, -1)
            return np.round(a * 100).astype(int)

        if first_idx < len(prices):
            row_prices = prices[first_idx]
            row_sizes = sizes[first_idx]
            cents_arr = safe_cents(row_prices)
            mask = (cents_arr == target_cents) & (row_sizes > 0)
            initial_size = float(row_sizes[mask].sum()) if mask.any() else 0.0
        else:
            initial_size = 0.0

        # Get level size at last_fill (this is what remains AFTER our fills consumed)
        last_fill_idx = max(0, np.searchsorted(ts_s, last_fill_s, side="left"))
        last_fill_idx = min(last_fill_idx, len(prices) - 1)
        row_prices = prices[last_fill_idx]
        row_sizes = sizes[last_fill_idx]
        cents_arr = safe_cents(row_prices)
        mask = (cents_arr == target_cents) & (row_sizes > 0)
        level_at_last_fill = float(row_sizes[mask].sum()) if mask.any() else 0.0

        # If level_at_last_fill ≈ 0, the order had no remaining quantity
        # (fully consumed or all our shares from initial). Treat as "FILLED_FULL"
        # and skip cancel inference unless level reappears then vanishes.
        if level_at_last_fill < 0.5:
            cls = "FILLED_FULL"
            results.append({
                **row.to_dict(),
                "classification": cls,
                "cancelled_ts": None,
                "lifetime_after_last_fill_s": 0.0,
                "lifetime_from_first_fill_s": last_fill_s - first_fill_s,
                "best_bid_post": float(bp[first_idx, 0]) if first_idx < len(bp) else np.nan,
                "best_bid_cancel": np.nan,
                "bb_displacement_cents": np.nan,
                "initial_level_size": initial_size,
                "level_at_last_fill": level_at_last_fill,
            })
            continue

        # Walk forward AFTER last_fill: did level drop significantly?
        # We say "cancel" when the level shrinks by ≥ 50% of level_at_last_fill
        # WITHOUT a matching fill in our trades (i.e. someone else cancelled
        # OR our wallet cancelled). We assume our wallet, since the order has
        # no further fills attributed to us.
        threshold = max(0.5, level_at_last_fill * 0.5)
        for i in range(after_idx, len(ts_s)):
            snap_ts = ts_s[i]
            row_prices = prices[i]
            row_sizes = sizes[i]
            cents_arr = safe_cents(row_prices)
            mask = (cents_arr == target_cents) & (row_sizes > 0)
            level_size = float(row_sizes[mask].sum()) if mask.any() else 0.0

            # Level shrunk significantly relative to last_fill level → cancel
            if level_at_last_fill - level_size >= threshold:
                cancelled_ts = snap_ts
                break
            # Stop searching past slot end
            if snap_ts > slot_end_s + 30:
                break

        # Get best_bid AT post-time and AT cancel-time (for H1 displacement test)
        # best_bid for SELL-side orders = bp[..., 0]; for BUY-side = bp[..., 0]
        # We use the wallet's price relative to best_bid
        bb_post = float(bp[first_idx, 0]) if first_idx < len(bp) else np.nan
        if cancelled_ts is not None:
            cancel_idx = np.searchsorted(ts_s, cancelled_ts, side="left")
            cancel_idx = min(cancel_idx, len(bp) - 1)
            bb_cancel = float(bp[cancel_idx, 0])
        else:
            bb_cancel = np.nan

        # Classify
        if cancelled_ts is not None:
            if cancelled_ts <= slot_end_s:
                cls = "CANCELLED"
            else:
                cls = "EXPIRED_NOSEEN"
            lifetime_after_last_fill = cancelled_ts - last_fill_s
            lifetime_from_first_fill = cancelled_ts - first_fill_s
        else:
            # Level persists past slot_end → expired
            cls = "EXPIRED"
            lifetime_after_last_fill = slot_end_s - last_fill_s
            lifetime_from_first_fill = slot_end_s - first_fill_s

        results.append({
            **row.to_dict(),
            "classification": cls,
            "cancelled_ts": cancelled_ts,
            "lifetime_after_last_fill_s": lifetime_after_last_fill,
            "lifetime_from_first_fill_s": lifetime_from_first_fill,
            "best_bid_post": bb_post,
            "best_bid_cancel": bb_cancel,
            "bb_displacement_cents": (bb_cancel - bb_post) * 100 if not np.isnan(bb_cancel) else np.nan,
            "initial_level_size": initial_size,
            "level_at_last_fill": level_at_last_fill,
        })

    res_df = pd.DataFrame(results)
    print(f"\n  Classification breakdown:")
    print(res_df["classification"].value_counts().to_string())

    out_path = cache / f"_cancel_inference_{asset.lower()}.parquet"
    res_df.to_parquet(out_path, index=False)
    print(f"  → {out_path}")

    # Summary stats
    valid = res_df[res_df.classification.isin(["CANCELLED", "EXPIRED"])]
    if len(valid):
        n_can = (valid.classification == "CANCELLED").sum()
        n_exp = (valid.classification == "EXPIRED").sum()
        print(f"\n  CANCELLED: {n_can} ({n_can/len(valid)*100:.1f}%)")
        print(f"  EXPIRED:   {n_exp} ({n_exp/len(valid)*100:.1f}%)")

    canc = res_df[res_df.classification == "CANCELLED"]
    if len(canc):
        print(f"\n  Cancel lifetime (sec from last_fill):")
        for q in [10, 25, 50, 75, 90, 99]:
            v = canc["lifetime_after_last_fill_s"].quantile(q / 100)
            print(f"    p{q}: {v:.1f}s")
        print(f"\n  Cancel lifetime (sec from first_fill):")
        for q in [10, 25, 50, 75, 90, 99]:
            v = canc["lifetime_from_first_fill_s"].quantile(q / 100)
            print(f"    p{q}: {v:.1f}s")
        # H1 test: book displacement distribution
        print(f"\n  Best-bid displacement at cancel (cents):")
        disp = canc["bb_displacement_cents"].dropna()
        if len(disp):
            for q in [10, 25, 50, 75, 90]:
                v = disp.quantile(q / 100)
                print(f"    p{q}: {v:.2f}¢")
            print(f"    |disp| mean: {disp.abs().mean():.2f}¢, std: {disp.std():.2f}")
        # H3 test: was there a fill before cancel?
        canc_with_fill = canc[canc.n_fills > 0]
        print(f"\n  Cancelled WITH prior fills: {len(canc_with_fill)}/{len(canc)} ({len(canc_with_fill)/len(canc)*100:.1f}%)")
        # Of those with fills, how long after the last fill did they cancel?
        if len(canc_with_fill):
            print(f"  Of those, time from last_fill to cancel:")
            for q in [25, 50, 75]:
                v = canc_with_fill["lifetime_after_last_fill_s"].quantile(q / 100)
                print(f"    p{q}: {v:.1f}s")

    return res_df


if __name__ == "__main__":
    wallets = sys.argv[1:] or ["0x04b6d7e9", "0xb27bc932"]
    summaries = {}
    for w in wallets:
        try:
            r = decode_wallet(w, n_sample=int(__import__("os").environ.get("N_SAMPLE", "300")))
            if r is not None:
                summaries[w] = r
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ERROR for {w}: {e}")
