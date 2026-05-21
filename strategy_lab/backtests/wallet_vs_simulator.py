"""
Wallet-vs-simulator comparator.

For each wallet × strategy × slug:
  - Wallet actual: fills count, sides, sizes, prices, leftover, PnL
  - Simulator: same metrics
  - Diff

Output:
  strategy_lab/backtests/_wallet_vs_sim.csv
  strategy_lab/backtests/_wallet_vs_sim_summary.json
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions


def wallet_per_slug_pnl(wallet_short: str) -> pd.DataFrame:
    """Per-slug ACTUAL wallet PnL using markets.parquet."""
    p = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / wallet_short / "markets.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    # PnL = cash from trading - cost of mint + leftover redeemed (winning side)
    # cash_total already nets trading inflows-outflows for the wallet
    # minted_pairs is the cost they paid to mint (= $1 each)
    df["mint_cost"] = df["minted_pairs"].fillna(0)
    df["trading_cash"] = df["cash_total"].fillna(0)
    return df


def main():
    # Load wallet ground truth
    wallets = ["0x04b6d7e9", "0xeebde7a0", "0x89b5cdaa", "0xcfb103c3", "0xce25e214"]
    wallet_dfs = {}
    for w in wallets:
        df = wallet_per_slug_pnl(w)
        if df.empty:
            continue
        wallet_dfs[w] = df

    # Load chainlink resolutions for outcome truth
    res = load_resolutions(assets=["BTC", "ETH", "SOL"])
    slug_outcome = dict(zip(res["slug"], res["outcome"]))

    # Compute wallet PnL per slug (need to know outcome to redeem winning side)
    rows = []
    for w, df in wallet_dfs.items():
        for _, r in df.iterrows():
            slug = r["slug"]
            outcome = slug_outcome.get(slug, "?")
            mint = float(r["mint_cost"])
            cash = float(r["trading_cash"])
            up_left = float(r.get("up_leftover", 0))
            dn_left = float(r.get("down_leftover", 0))
            redeemed = up_left if outcome == "Up" else dn_left if outcome == "Down" else 0
            # Note: leftover can be positive (have shares) or negative
            # Negative = sold short or oversold. We can only redeem positive.
            redeemed = max(redeemed, 0)
            pnl = cash + redeemed * 1.0 - mint
            rows.append({
                "wallet": w, "slug": slug, "outcome_truth": outcome,
                "mint_cost": mint, "trading_cash": cash,
                "up_leftover": up_left, "down_leftover": dn_left,
                "redeemed": redeemed, "actual_pnl": pnl,
                "mc": r.get("mc"), "asset_sym": r.get("asset_sym"),
                "slot_start_s": r.get("slot_start_s"),
            })
    wdf = pd.DataFrame(rows)
    wdf.to_csv(OUT_DIR / "_wallet_actual_pnl.csv", index=False)

    # Summary per wallet
    print()
    print("=" * 80)
    print("WALLET ACTUAL PnL (per-slug + aggregate)")
    print("=" * 80)
    summary = wdf.groupby("wallet").agg(
        n_slugs=("slug", "count"),
        mean_pnl=("actual_pnl", "mean"),
        median_pnl=("actual_pnl", "median"),
        sum_pnl=("actual_pnl", "sum"),
        pct_positive=("actual_pnl", lambda s: (s > 0).mean() * 100),
        median_mint=("mint_cost", "median"),
        median_cash=("trading_cash", "median"),
        median_redeemed=("redeemed", "median"),
    ).reset_index()
    print(summary.to_string(index=False))

    summary.to_csv(OUT_DIR / "_wallet_actual_pnl_summary.csv", index=False)


if __name__ == "__main__":
    main()
