"""Analyze a wallet's chain-pulled trades, filtered to up-down 5m/15m markets.

Joins trades_chain.parquet → _token_lookup.parquet → market_class + slug.
Fixes decoder edge cases (drops invalid prices). Then runs strategy
fingerprint focused on up-down behavior.

Usage:
    py -3 strategy_lab/wallet_hunt/analyze_chain.py --wallet 0x...
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

CACHE = Path(__file__).resolve().parent / "cache"
LOOKUP_PATH = CACHE / "_token_lookup.parquet"

SLUG_UD = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")


def join_market_metadata(trades: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
    """Join chain trades to market metadata via asset_id."""
    out = trades.merge(
        lookup[["asset_id", "condition_id", "slug", "outcome", "market_class", "mkt_asset"]],
        left_on="asset", right_on="asset_id", how="left",
    )
    # Extract slot_start from slug
    def parse_slot(slug):
        if not isinstance(slug, str):
            return None
        m = SLUG_UD.match(slug)
        return int(m.group(3)) if m else None
    out["slot_start_s"] = out.slug.map(parse_slot)
    return out


def fix_side_mapping(df: pd.DataFrame, wallet: str) -> pd.DataFrame:
    """Re-derive BUY/SELL using the cleaner rule.

    For a binary-outcome trade:
      wallet receives shares (outcome token) ↔ BUY
      wallet receives USDC ↔ SELL

    The Polymarket NegRisk matcher emits one OrderFilled per fill against
    each counterparty. In each event:
      - Either makerAssetId is the outcome token (large uint256) and takerAssetId
        encodes the USDC payment / price
      - Or vice-versa
    """
    w = wallet.lower()
    df = df.copy()
    df["wallet_is_maker"] = df.maker.str.lower() == w
    df["wallet_is_taker"] = df.taker.str.lower() == w

    # The asset column we already populated by join_market_metadata is the
    # actual outcome token. Whichever side HOLDS that token (in this fill) is
    # the SELLER.
    df["maker_holds_token"] = df.maker_asset_id.astype(str) == df.asset.astype(str)
    df["taker_holds_token"] = df.taker_asset_id_raw.astype(str) == df.asset.astype(str)

    def fix_side(r):
        # Buyer = the side that DOESN'T hold the token (they provide USDC)
        # If wallet doesn't hold the token in this fill → wallet is buying
        if r.wallet_is_maker and r.taker_holds_token:
            return "BUY"
        if r.wallet_is_taker and r.maker_holds_token:
            return "BUY"
        if r.wallet_is_maker and r.maker_holds_token:
            return "SELL"
        if r.wallet_is_taker and r.taker_holds_token:
            return "SELL"
        return None

    df["side_clean"] = df.apply(fix_side, axis=1)

    # Price: the non-token assetId / 1e7 (when token is huge, the OTHER field
    # encodes price; their respective amounts are USDC and shares scaled by 1e6)
    def fix_price(r):
        try:
            if r.maker_holds_token:
                return int(r.taker_asset_id_raw) / 1e7
            if r.taker_holds_token:
                return int(r.maker_asset_id) / 1e7
        except (ValueError, TypeError):
            return None
        return None

    df["price_clean"] = df.apply(fix_price, axis=1)

    # Size: the share amount = whichever AMOUNT corresponds to the token side
    def fix_size(r):
        try:
            if r.maker_holds_token:
                return int(r.maker_amount_raw) / 1e6
            if r.taker_holds_token:
                return int(r.taker_amount_raw) / 1e6
        except (ValueError, TypeError):
            return None
        return None

    df["size_clean"] = df.apply(fix_size, axis=1)
    df["usd_clean"] = df.size_clean * df.price_clean

    return df


def fingerprint(trades: pd.DataFrame, label: str) -> None:
    """Print a behavioral fingerprint of a chain trade DataFrame."""
    if trades.empty:
        print(f"  {label}: empty")
        return
    print(f"\n=== {label} ===")
    print(f"  n_trades: {len(trades):,}")
    if "timestamp" in trades.columns:
        ts = pd.to_datetime(trades.timestamp, unit="s", utc=True)
        print(f"  window:   {ts.min()} → {ts.max()}  ({(ts.max()-ts.min()).total_seconds()/3600:.1f}h)")
    print(f"  unique conditions: {trades.condition_id.nunique():,}")
    side_counts = trades.side_clean.value_counts(dropna=False).to_dict()
    print(f"  side: {side_counts}")
    print(f"  liquidity: maker_pct={trades.wallet_is_maker.mean()*100:.1f}%")
    if "size_clean" in trades.columns:
        s = trades.size_clean.dropna()
        if len(s):
            print(f"  size (shares):   p25={s.quantile(0.25):.2f}  med={s.median():.2f}  p75={s.quantile(0.75):.2f}  p95={s.quantile(0.95):.2f}  max={s.max():.2f}")
        u = trades.usd_clean.dropna()
        if len(u):
            print(f"  notional (USDC): p25=${u.quantile(0.25):.2f}  med=${u.median():.2f}  p75=${u.quantile(0.75):.2f}  total=${u.sum():,.2f}")
        p = trades.price_clean.dropna()
        if len(p):
            print(f"  price:           p25={p.quantile(0.25):.4f}  med={p.median():.4f}  p75={p.quantile(0.75):.4f}")
    if "market_class" in trades.columns:
        print(f"  market class:")
        for k, v in trades.market_class.value_counts().items():
            pct = v / len(trades) * 100
            print(f"    {k:<16} {v:>6} ({pct:.1f}%)")
    if "mkt_asset" in trades.columns:
        ud = trades[trades.market_class.fillna("").str.startswith("updown_")]
        if len(ud):
            print(f"  asset/tf breakdown (up-down only):")
            print(ud.groupby(["mkt_asset", "market_class"]).size().to_string())


def per_leg_analysis(trades: pd.DataFrame, wallet: str) -> pd.DataFrame:
    """Aggregate by (condition_id, outcome) — one row per leg."""
    ud = trades[trades.market_class.fillna("").str.startswith("updown_") &
                trades.side_clean.notna() &
                trades.price_clean.between(0, 1, inclusive="neither")].copy()
    if ud.empty:
        return ud

    ud["slot_start_s"] = ud.slot_start_s.astype("Int64")
    ud["window_s"] = ud.market_class.map({"updown_5m": 300, "updown_15m": 900}).astype("Int64")
    ud["offset_s"] = ud.timestamp.astype("Int64") - ud.slot_start_s

    grp = ud.groupby(["condition_id", "outcome"], as_index=False)
    legs = grp.agg(
        slug=("slug", "first"),
        market_class=("market_class", "first"),
        mkt_asset=("mkt_asset", "first"),
        slot_start_s=("slot_start_s", "first"),
        n_trades=("side_clean", "size"),
        n_buys=("side_clean", lambda s: (s == "BUY").sum()),
        n_sells=("side_clean", lambda s: (s == "SELL").sum()),
        buy_shares=("size_clean", lambda s: ud.loc[s.index].loc[ud.side_clean == "BUY", "size_clean"].sum()),
        sell_shares=("size_clean", lambda s: ud.loc[s.index].loc[ud.side_clean == "SELL", "size_clean"].sum()),
        buy_usd=("usd_clean", lambda s: ud.loc[s.index].loc[ud.side_clean == "BUY", "usd_clean"].sum()),
        sell_usd=("usd_clean", lambda s: ud.loc[s.index].loc[ud.side_clean == "SELL", "usd_clean"].sum()),
        avg_buy_px=("price_clean", lambda s: ud.loc[s.index].loc[ud.side_clean == "BUY", "price_clean"].mean()),
        avg_sell_px=("price_clean", lambda s: ud.loc[s.index].loc[ud.side_clean == "SELL", "price_clean"].mean()),
        first_ts=("timestamp", "min"),
        last_ts=("timestamp", "max"),
        first_offset=("offset_s", "min"),
        last_offset=("offset_s", "max"),
    )
    legs["leftover_shares"] = legs.buy_shares - legs.sell_shares
    legs["net_cash"] = legs.sell_usd - legs.buy_usd  # negative = still long
    return legs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    args = ap.parse_args()
    w = args.wallet.lower()
    short = w[:10]

    cp = CACHE / short / "trades_chain.parquet"
    if not cp.exists():
        print(f"missing {cp} — run fetch_chain.py first")
        return 1

    trades = pd.read_parquet(cp)
    lookup = pd.read_parquet(LOOKUP_PATH)
    print(f"=== {short}: {len(trades):,} chain trades; lookup has {len(lookup):,} assets")

    trades = join_market_metadata(trades, lookup)
    matched = trades.slug.notna().sum()
    print(f"  asset_id matched to slug: {matched}/{len(trades)} ({100*matched/len(trades):.1f}%)")

    trades = fix_side_mapping(trades, w)
    valid = ((trades.side_clean.notna()) &
             (trades.price_clean.between(0, 1, inclusive="neither")))
    print(f"  trades with valid side + price (0,1): {valid.sum()}/{len(trades)} ({100*valid.mean():.1f}%)")

    trades.to_parquet(CACHE / short / "trades_chain_enriched.parquet", index=False)

    # Overall fingerprint
    fingerprint(trades, "ALL chain trades (after decode fix)")

    # Up-down only
    ud = trades[trades.market_class.fillna("").str.startswith("updown_")]
    fingerprint(ud, "UP-DOWN 5m/15m only")

    # 5m only
    fingerprint(ud[ud.market_class == "updown_5m"], "UP-DOWN 5m ONLY")
    # 15m only
    fingerprint(ud[ud.market_class == "updown_15m"], "UP-DOWN 15m ONLY")

    # Per-leg analysis (up-down only)
    legs = per_leg_analysis(trades, w)
    if not legs.empty:
        legs.to_parquet(CACHE / short / "per_leg_chain.parquet", index=False)
        print(f"\n=== per-leg up-down analysis ({len(legs):,} legs) ===")
        print(f"  legs by market_class: {legs.market_class.value_counts().to_dict()}")
        print(f"  avg_trades_per_leg (UD): {legs.n_trades.mean():.1f}")
        print(f"  pct legs only-BUY:  {100 * (legs.n_sells == 0).mean():.1f}%")
        print(f"  pct legs only-SELL: {100 * (legs.n_buys == 0).mean():.1f}%")
        print(f"  pct legs both:      {100 * ((legs.n_buys > 0) & (legs.n_sells > 0)).mean():.1f}%")
        print(f"  median first_offset (s after slot_start): {legs.first_offset.median():.1f}")
        print(f"  median last_offset:                       {legs.last_offset.median():.1f}")
        print()
        print("=== top 10 legs by n_trades ===")
        cols = ["slug", "outcome", "n_trades", "n_buys", "n_sells",
                 "avg_buy_px", "avg_sell_px", "buy_shares", "sell_shares",
                 "leftover_shares", "net_cash"]
        print(legs.sort_values("n_trades", ascending=False).head(10)[cols].round(3).to_string(index=False))

    print("\nDone.")


if __name__ == "__main__":
    main()
