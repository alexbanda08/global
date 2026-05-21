"""
Per-fill profitability by within-slug offset.

For 0xcfb103c3 (the PAT taker we want to replicate), compute:
  - Per-slug net PnL (from per_leg.parquet or pnl.parquet)
  - Bucket each slug by the offset of the wallet's FIRST fill on that slug
  - Compare PnL distribution across early-bucket vs late-bucket slugs

Also computes "is early-slug fire profitable per-fill" via paired fill matching
where possible.

Outputs:
  _timing_profitability_per_slug.csv
  _timing_profitability_summary.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"
CACHE_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache"


def per_slug_pnl(wallet: str) -> pd.DataFrame:
    """Compute realized cash PnL per slug from fills + trades_chain.
    PnL = sum(sell_usd) - sum(buy_usd) + redeemed_usd (if any)."""
    fills_p = CACHE_DIR / wallet / "fills.parquet"
    if not fills_p.exists():
        return pd.DataFrame()
    fills = pd.read_parquet(fills_p)
    fills = fills[fills["asset_sym"].str.upper() == "BTC"].copy()
    if fills.empty:
        return pd.DataFrame()
    fills["tf"] = fills["slug"].str.extract(r"-(\d+m)-")[0]
    fills["window_s"] = fills["tf"].map({"5m": 300, "15m": 900}).fillna(300)

    # Per-slug aggregates
    fills["signed_usd"] = np.where(
        fills["side"].str.upper() == "SELL", fills["usd"], -fills["usd"])
    g = fills.groupby("slug").agg(
        n_fills=("usd", "size"),
        n_buys=("side", lambda s: (s.str.upper() == "BUY").sum()),
        n_sells=("side", lambda s: (s.str.upper() == "SELL").sum()),
        n_maker=("is_maker", lambda s: s.sum()),
        first_offset_s=("offset_from_slot_start_s", "min"),
        last_offset_s=("offset_from_slot_start_s", "max"),
        cash_flow_usd=("signed_usd", "sum"),
        tf=("tf", "first"),
        window_s=("window_s", "first"),
        slot_start_s=("slot_start_s", "first"),
    ).reset_index()

    # Add redeemed USDC (from positions.parquet or per_leg if available)
    pnl_p = CACHE_DIR / wallet / "pnl.parquet"
    if pnl_p.exists():
        pnl = pd.read_parquet(pnl_p)
        if "slug" in pnl.columns and "realized_pnl_usdc" in pnl.columns:
            slug_pnl = pnl.groupby("slug")["realized_pnl_usdc"].sum().reset_index()
            slug_pnl = slug_pnl.rename(columns={"realized_pnl_usdc": "chain_pnl"})
            g = g.merge(slug_pnl, on="slug", how="left")
        elif "slug" in pnl.columns and "cash_pnl_usdc" in pnl.columns:
            slug_pnl = pnl.groupby("slug")["cash_pnl_usdc"].sum().reset_index()
            slug_pnl = slug_pnl.rename(columns={"cash_pnl_usdc": "chain_pnl"})
            g = g.merge(slug_pnl, on="slug", how="left")

    # Bucket the first-fill offset
    def bucket(o):
        if pd.isna(o):
            return "?"
        if o < 30: return "0-30s"
        if o < 60: return "30-60s"
        if o < 120: return "60-120s"
        if o < 180: return "120-180s"
        return "180s+"
    g["first_fill_bucket"] = g["first_offset_s"].apply(bucket)
    g["wallet"] = wallet
    return g


def main():
    wallets = ["0x04b6d7e9", "0xeebde7a0", "0x89b5cdaa", "0xcfb103c3", "0xce25e214"]
    parts = []
    summary_rows = []
    for w in wallets:
        ps = per_slug_pnl(w)
        if ps.empty:
            print(f"  SKIP {w}")
            continue
        parts.append(ps)

        # Summary per wallet × tf × bucket
        for tf in ["5m", "15m"]:
            sub = ps[ps["tf"] == tf]
            if sub.empty:
                continue
            for bk in ["0-30s", "30-60s", "60-120s", "120-180s", "180s+"]:
                bksub = sub[sub["first_fill_bucket"] == bk]
                if bksub.empty:
                    continue
                # Use cash_flow_usd as PnL proxy (since chain_pnl may not be present)
                pnl_col = "chain_pnl" if "chain_pnl" in bksub.columns and \
                          bksub["chain_pnl"].notna().any() else "cash_flow_usd"
                vals = bksub[pnl_col].dropna()
                if vals.empty:
                    continue
                summary_rows.append({
                    "wallet": w,
                    "tf": tf,
                    "first_fill_bucket": bk,
                    "n_slugs": int(len(bksub)),
                    "pnl_mean": round(float(vals.mean()), 4),
                    "pnl_median": round(float(vals.median()), 4),
                    "pnl_sum": round(float(vals.sum()), 2),
                    "win_rate_pct": round(float((vals > 0).mean() * 100), 2),
                    "pnl_col_used": pnl_col,
                })

    all_per_slug = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    all_per_slug.to_csv(OUT_DIR / "_timing_profitability_per_slug.csv", index=False)
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "_timing_profitability_summary.csv", index=False)

    print(f"\nWrote {OUT_DIR / '_timing_profitability_per_slug.csv'} ({len(all_per_slug)} rows)")
    print(f"Wrote {OUT_DIR / '_timing_profitability_summary.csv'} ({len(summary)} rows)")
    print()
    print("=" * 95)
    print("WALLET PnL/SLUG BY FIRST-FILL OFFSET BUCKET")
    print("=" * 95)
    for w in wallets:
        sw = summary[summary["wallet"] == w]
        if sw.empty:
            continue
        print(f"\n{w}:")
        cols = ["tf", "first_fill_bucket", "n_slugs", "pnl_mean",
                "pnl_median", "pnl_sum", "win_rate_pct", "pnl_col_used"]
        print(sw[cols].to_string(index=False))


if __name__ == "__main__":
    main()
