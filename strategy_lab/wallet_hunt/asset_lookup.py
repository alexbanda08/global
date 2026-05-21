"""Build a token_id → (condition_id, slug, outcome) lookup from data we have.

Sources (in priority order):
  1. clob_resolutions_cache.parquet — 18k+ markets with up_token_id, down_token_id
  2. Per-wallet trades.parquet (data-api) — has asset, conditionId, slug, outcome
  3. Live CLOB /markets/<condition_id> for unknown markets (slow fallback)

Output: cache/_token_lookup.parquet with columns:
  asset_id (str), condition_id (str), slug (str), outcome (Up/Down),
  market_class (updown_5m/updown_15m/other), mkt_asset (BTC/ETH/SOL)
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

CACHE = Path(__file__).resolve().parent / "cache"

SLUG_UD = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")


def classify_slug(slug):
    if not isinstance(slug, str):
        return ("unknown", None)
    m = SLUG_UD.match(slug)
    if m:
        return (f"updown_{m.group(2)}", m.group(1).upper())
    return ("other", None)


def build_lookup() -> pd.DataFrame:
    rows = []

    # Source 1: CLOB resolutions cache
    clob_p = ROOT / "data" / "v4" / "canonical" / "clob_resolutions_cache.parquet"
    if clob_p.exists():
        clob = pd.read_parquet(clob_p)
        print(f"  CLOB cache: {len(clob)} markets")
        for _, r in clob.iterrows():
            if pd.notna(r.get("up_token_id")) and r["up_token_id"]:
                rows.append({
                    "asset_id": str(r["up_token_id"]),
                    "condition_id": r["condition_id"],
                    "slug": r.get("slug"),
                    "outcome": "Up",
                })
            if pd.notna(r.get("down_token_id")) and r["down_token_id"]:
                rows.append({
                    "asset_id": str(r["down_token_id"]),
                    "condition_id": r["condition_id"],
                    "slug": r.get("slug"),
                    "outcome": "Down",
                })

    # Source 2: per-wallet data-api trades
    for wallet_dir in sorted(CACHE.glob("0x*")):
        tp = wallet_dir / "trades.parquet"
        if not tp.exists():
            continue
        t = pd.read_parquet(tp)
        if "asset" not in t.columns:
            continue
        seen = t[["asset", "conditionId", "slug", "outcome"]].drop_duplicates("asset")
        for _, r in seen.iterrows():
            rows.append({
                "asset_id": str(r["asset"]),
                "condition_id": r["conditionId"],
                "slug": r["slug"],
                "outcome": r["outcome"],
            })
        print(f"  data-api ({wallet_dir.name}): added {len(seen)} unique assets")

    df = pd.DataFrame(rows).drop_duplicates("asset_id", keep="first").reset_index(drop=True)
    cls = df.slug.map(classify_slug)
    df["market_class"] = cls.map(lambda x: x[0])
    df["mkt_asset"] = cls.map(lambda x: x[1])
    return df


if __name__ == "__main__":
    df = build_lookup()
    out = CACHE / "_token_lookup.parquet"
    df.to_parquet(out, index=False)
    print(f"\n=== {len(df):,} unique asset_ids in lookup")
    print(f"  saved -> {out}")
    print(df.market_class.value_counts().to_string())
    print()
    ud = df[df.market_class.str.startswith("updown_")]
    print(f"  up-down markets: {len(ud):,}")
    print(f"  by (mkt_asset, market_class):")
    print(ud.groupby(["mkt_asset", "market_class"]).size().to_string())
