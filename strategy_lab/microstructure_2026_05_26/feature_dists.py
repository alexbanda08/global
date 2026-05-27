"""Compute feature distribution stats per asset (for report section 2)."""
from __future__ import annotations
import sys, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")
WORK = ROOT / "strategy_lab" / "microstructure_2026_05_26"


def main():
    parts = []
    for asset in ["BTC", "ETH", "SOL"]:
        p = WORK / f"micro_panel_{asset.lower()}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
    panel = pd.concat(parts, ignore_index=True)
    print(f"panel rows: {len(panel)}")

    # Feature columns to summarize
    feat_cols = [
        "up_spread_bps", "dn_spread_bps",
        "up_imb5", "dn_imb5",
        "up_imb25", "dn_imb25",
        "up_micro_dev_bps", "dn_micro_dev_bps",
        "up_depth_2pct", "dn_depth_2pct",
        "up_queue_top_bid", "dn_queue_top_bid",
        "up_quote_intensity_5s", "dn_quote_intensity_5s",
        "up_book_dt_us", "dn_book_dt_us",
        "imb5_diff", "micro_dev_diff", "spread_diff",
    ]

    rows = []
    for asset in ["BTC", "ETH", "SOL"]:
        sub = panel[panel.asset == asset]
        for f in feat_cols:
            if f not in sub.columns:
                continue
            s = sub[f].dropna()
            if len(s) == 0:
                continue
            rows.append({
                "asset": asset, "feature": f,
                "n": len(s),
                "mean": float(s.mean()),
                "median": float(s.median()),
                "p10": float(s.quantile(0.10)),
                "p90": float(s.quantile(0.90)),
                "std": float(s.std()),
            })
    df = pd.DataFrame(rows)
    df.to_csv(WORK / "feature_distributions.csv", index=False)
    print(df.to_string())


if __name__ == "__main__":
    main()
