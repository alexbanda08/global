"""
Timing × CHAIN-TRUTH PnL.

Uses pnl.parquet's pnl_net (chain-derived per-slug PnL including mint cost,
redemption, fees) — the only honest metric.

Bucketizes each wallet's slugs by FIRST-FILL OFFSET and compares pnl_net
distribution across buckets.

Outputs:
  _timing_truth_pnl_per_slug.csv
  _timing_truth_pnl_summary.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"
CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache"

WALLETS = [
    ("0x04b6d7e9", "MAS"),
    ("0xeebde7a0", "HYBRID (Bonereaper)"),
    ("0x89b5cdaa", "directional MAS (ohanism)"),
    ("0xcfb103c3", "PAT (xuanxuan008)"),
    ("0xce25e214", "mixed taker"),
]


def first_fill_offset(wallet: str) -> pd.DataFrame:
    fills = pd.read_parquet(CACHE / wallet / "fills.parquet")
    fills = fills[fills.asset_sym.str.upper() == "BTC"].copy()
    if fills.empty:
        return pd.DataFrame()
    fills["tf"] = fills["slug"].str.extract(r"-(\d+m)-")[0]
    fills["is_taker_buy"] = (
        (fills["is_maker"] == False) & (fills["side"].str.upper() == "BUY"))
    fills["is_maker_sell"] = (
        (fills["is_maker"] == True) & (fills["side"].str.upper() == "SELL"))
    g = fills.groupby("slug").agg(
        first_offset_s=("offset_from_slot_start_s", "min"),
        last_offset_s=("offset_from_slot_start_s", "max"),
        n_fills=("offset_from_slot_start_s", "size"),
        n_taker_buys=("is_taker_buy", "sum"),
        n_maker_sells=("is_maker_sell", "sum"),
        tf=("tf", "first"),
    ).reset_index()
    return g


def bucket_offset(o):
    if pd.isna(o):
        return "?"
    if o < 30:   return "0-30s"
    if o < 60:   return "30-60s"
    if o < 120:  return "60-120s"
    if o < 180:  return "120-180s"
    if o < 240:  return "180-240s"
    return "240s+"


def main():
    all_rows = []
    summary_rows = []
    for wallet, tag in WALLETS:
        pnl_p = CACHE / wallet / "pnl.parquet"
        if not pnl_p.exists():
            continue
        pnl = pd.read_parquet(pnl_p)
        pnl = pnl[pnl.asset_sym.str.upper() == "BTC"].copy()
        if pnl.empty:
            continue
        ff = first_fill_offset(wallet)
        if ff.empty:
            continue
        merged = pnl.merge(ff, on="slug", how="left")
        merged["wallet"] = wallet
        merged["label"] = tag
        merged["first_fill_bucket"] = merged.first_offset_s.apply(bucket_offset)

        # Get tf from merged.tf if exists, else infer from slug
        merged["tf_x"] = merged.get("tf",
            merged["slug"].str.extract(r"-(\d+m)-")[0])

        all_rows.append(merged)

        # Per-bucket × tf summary
        for tf in ["5m", "15m"]:
            sub = merged[merged.tf_x == tf]
            if sub.empty:
                continue
            for bk in ["0-30s", "30-60s", "60-120s", "120-180s", "180-240s", "240s+"]:
                bksub = sub[sub.first_fill_bucket == bk]
                if bksub.empty:
                    continue
                summary_rows.append({
                    "wallet": wallet,
                    "label": tag,
                    "tf": tf,
                    "first_fill_bucket": bk,
                    "n_slugs": int(len(bksub)),
                    "pnl_net_mean": round(float(bksub.pnl_net.mean()), 4),
                    "pnl_net_median": round(float(bksub.pnl_net.median()), 4),
                    "pnl_net_sum": round(float(bksub.pnl_net.sum()), 2),
                    "pnl_gross_mean": round(float(bksub.pnl_gross.mean()), 4),
                    "fees_mean": round(float(bksub.fees.mean()), 4),
                    "win_rate_pct": round(float((bksub.pnl_net > 0).mean() * 100), 2),
                    "minted_pairs_mean": round(float(bksub.minted_pairs.mean()), 2),
                    "n_taker_buys_avg": round(float(bksub.n_taker_buys.mean()), 1),
                    "n_maker_sells_avg": round(float(bksub.n_maker_sells.mean()), 1),
                })

    if all_rows:
        all_df = pd.concat(all_rows, ignore_index=True)
        cols_keep = [c for c in [
            "wallet", "label", "slug", "tf_x", "slot_start_s",
            "first_offset_s", "last_offset_s", "first_fill_bucket",
            "n_fills", "n_taker_buys", "n_maker_sells",
            "minted_pairs", "cash_total", "winner", "resolved",
            "pnl_gross", "fees", "pnl_net"] if c in all_df.columns]
        all_df[cols_keep].to_csv(OUT_DIR / "_timing_truth_pnl_per_slug.csv", index=False)

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "_timing_truth_pnl_summary.csv", index=False)

    print(f"\nWrote {OUT_DIR / '_timing_truth_pnl_summary.csv'} ({len(summary)} rows)")
    print()
    print("=" * 110)
    print("CHAIN-TRUTH PnL BY FIRST-FILL OFFSET BUCKET (pnl_net = gross - fees, includes mint+redeem)")
    print("=" * 110)
    for wallet, tag in WALLETS:
        sw = summary[summary.wallet == wallet]
        if sw.empty:
            continue
        print(f"\n{wallet} ({tag}):")
        cols = ["tf", "first_fill_bucket", "n_slugs",
                "pnl_net_mean", "pnl_net_median", "pnl_net_sum",
                "win_rate_pct", "minted_pairs_mean",
                "n_taker_buys_avg", "n_maker_sells_avg"]
        print(sw[cols].to_string(index=False))

    # Print a cross-wallet summary on the key insight: does 0-30s have edge?
    print()
    print("=" * 100)
    print("CROSS-WALLET: 0-30s bucket vs rest of slug (pnl_net per slug)")
    print("=" * 100)
    print(f"{'wallet':<15} {'tf':<5} {'n_0_30':>8} {'pnl_0_30':>12} "
          f"{'n_rest':>8} {'pnl_rest':>12} {'lift_x':>8}")
    for wallet, tag in WALLETS:
        for tf in ["5m", "15m"]:
            early = summary[(summary.wallet == wallet) & (summary.tf == tf) &
                            (summary.first_fill_bucket == "0-30s")]
            rest = summary[(summary.wallet == wallet) & (summary.tf == tf) &
                           (summary.first_fill_bucket != "0-30s")]
            if early.empty or rest.empty:
                continue
            e_pnl = float(early.pnl_net_mean.iloc[0])
            e_n = int(early.n_slugs.iloc[0])
            r_n = int(rest.n_slugs.sum())
            r_pnl = float((rest.pnl_net_mean * rest.n_slugs).sum() / max(r_n, 1))
            lift = e_pnl / r_pnl if abs(r_pnl) > 0.01 else float("nan")
            print(f"{wallet:<15} {tf:<5} {e_n:>8d} {e_pnl:>12.3f} "
                  f"{r_n:>8d} {r_pnl:>12.3f} {lift:>8.2f}")


if __name__ == "__main__":
    main()
