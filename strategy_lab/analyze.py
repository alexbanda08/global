"""
Analyze a sweep CSV:
  * Rank strategies by Calmar, Sharpe, and a composite score
  * Filter rows that have meaningful trade counts (≥ 20)
  * Pick top-N per (symbol, tf) and overall

Usage:
    python -m strategy_lab.analyze strategy_lab/results/sweep_<stamp>.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def composite_score(row: pd.Series) -> float:
    """Risk-adjusted composite: rewards Calmar + Sharpe, penalises <20 trades."""
    calmar = row.get("calmar", 0.0) or 0.0
    sharpe = row.get("sharpe", 0.0) or 0.0
    n = row.get("n_trades", 0) or 0
    trade_penalty = 0.5 if n < 20 else 1.0
    # Negative Calmar → negative score.
    return (calmar * 1.5 + sharpe * 1.0) * trade_penalty


def main(path: str) -> int:
    df = pd.read_csv(path)
    df["composite"] = df.apply(composite_score, axis=1)

    # Clean display
    cols = ["strategy", "symbol", "tf", "bars", "n_trades",
            "total_return", "cagr", "sharpe", "sortino",
            "calmar", "max_dd", "win_rate", "profit_factor",
            "bh_return", "composite"]
    df = df[cols].copy()

    # Format
    for c in ["total_return", "cagr", "sharpe", "sortino", "calmar",
              "max_dd", "win_rate", "profit_factor", "bh_return", "composite"]:
        df[c] = df[c].round(3)

    out = Path(path).with_suffix(".ranked.csv")
    df.sort_values("composite", ascending=False).to_csv(out, index=False)
    print(f"Saved ranked CSV → {out}")

    # Summary: top-3 per (symbol, tf)
    print("\n=== TOP 3 PER (SYMBOL, TF) by composite ===")
    top = (df.sort_values("composite", ascending=False)
             .groupby(["symbol", "tf"], group_keys=False)
             .head(3))
    print(top.to_string(index=False))

    # Summary: overall top 10 across all
    print("\n=== OVERALL TOP 10 by composite ===")
    print(df.sort_values("composite", ascending=False).head(10).to_string(index=False))

    # Summary: which strategies appear most frequently in top 3?
    print("\n=== Winners by strategy (appearances in top-3 blocks) ===")
    print(top["strategy"].value_counts().to_string())

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("pass path to sweep CSV")
    sys.exit(main(sys.argv[1]))
