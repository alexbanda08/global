"""
Fast portfolio ranking: loads the 28 pre-built equity curves from
phase5_results/equity_curves/perps/*.parquet and enumerates all 2-sleeve,
3-sleeve, and 4-sleeve combinations with vectorized daily-rebalanced EQW.

Writes:
  phase5_results/perps_portfolio_hunt.csv   — all combos scored
  phase5_results/perps_portfolio_top.csv    — top 30 by min-year return
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "research" / "phase5_results"
EQ = OUT / "equity_curves" / "perps"

BPY = 365.25 * 6        # 4h


def load_curves() -> dict[str, pd.Series]:
    out = {}
    for p in sorted(EQ.glob("*.parquet")):
        out[p.stem] = pd.read_parquet(p)["equity"]
    return out


def score_eqw_blend(rets_df: pd.DataFrame) -> dict:
    """Daily-rebalanced equal-weight blend. Returns Sharpe/CAGR/MDD + per-year."""
    port_rets = rets_df.mean(axis=1)
    port_eq = (1.0 + port_rets).cumprod()
    if len(port_eq) < 30:
        return {}
    mu, sd = float(port_rets.mean()), float(port_rets.std())
    sh = (mu / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    peak = port_eq.cummax()
    mdd = float((port_eq / peak - 1.0).min())
    years = (port_eq.index[-1] - port_eq.index[0]).total_seconds() / (365.25 * 86400)
    total = float(port_eq.iloc[-1] / port_eq.iloc[0] - 1)
    cagr = (1 + total) ** (1 / max(years, 1e-6)) - 1.0
    calmar = cagr / abs(mdd) if mdd != 0 else 0.0
    # per-year
    yearly = {}
    for yr in sorted(set(port_eq.index.year)):
        ye = port_eq[port_eq.index.year == yr]
        if len(ye) < 30:
            continue
        yearly[yr] = float(ye.iloc[-1] / ye.iloc[0] - 1)
    pos = sum(1 for v in yearly.values() if v > 0)
    return {
        "sharpe": round(sh, 3), "cagr": round(cagr, 4),
        "max_dd": round(mdd, 4), "calmar": round(calmar, 3),
        "min_yr": round(min(yearly.values()) if yearly else 0, 4),
        "max_yr": round(max(yearly.values()) if yearly else 0, 4),
        "pos_yrs": pos, "n_yrs": len(yearly),
        "yearly": {str(k): round(v, 4) for k, v in yearly.items()},
    }


def main():
    curves = load_curves()
    labels = sorted(curves.keys())
    print(f"Loaded {len(labels)} equity curves")

    # Align to common index and build returns matrix
    common = None
    for eq in curves.values():
        common = eq.index if common is None else common.intersection(eq.index)
    rets = pd.DataFrame({k: curves[k].reindex(common).pct_change().fillna(0)
                         for k in labels})
    print(f"Common bars: {len(rets)}  window: {rets.index[0].date()} -> {rets.index[-1].date()}")

    # Correlation
    corr = rets.corr()
    corr.round(3).to_csv(OUT / "perps_correlation_matrix.csv")

    # Enumerate 1-, 2-, 3-, 4-sleeve combos
    all_rows = []
    for size in (1, 2, 3, 4):
        combos = list(itertools.combinations(labels, size))
        print(f"Scoring {len(combos)} {size}-sleeve combos...")
        for combo in combos:
            m = score_eqw_blend(rets[list(combo)])
            if not m:
                continue
            if size > 1:
                sub = corr.loc[list(combo), list(combo)].values
                avg_corr = float(sub[np.triu_indices(size, k=1)].mean())
            else:
                avg_corr = 1.0
            all_rows.append({
                "size": size,
                "sleeves": " + ".join(combo),
                "avg_pair_corr": round(avg_corr, 3),
                **m,
            })

    df = pd.DataFrame(all_rows)
    df["yearly"] = df["yearly"].apply(json.dumps)
    df.to_csv(OUT / "perps_portfolio_hunt.csv", index=False)
    print(f"\nTotal combos scored: {len(df)}")

    # Rank by min_yr then sharpe, only 2+ sleeves
    multi = df[df["size"] >= 2].sort_values(
        ["min_yr", "sharpe"], ascending=[False, False]
    ).head(30)
    multi.to_csv(OUT / "perps_portfolio_top.csv", index=False)

    print("\n=== TOP 30 by worst-year return ===\n")
    with pd.option_context("display.width", 220, "display.max_colwidth", 70):
        cols = ["size", "sleeves", "sharpe", "cagr", "max_dd", "calmar",
                "min_yr", "pos_yrs", "n_yrs", "avg_pair_corr"]
        print(multi[cols].to_string(index=False))

    # Also show top 10 by Sharpe alone
    top_sh = df[df["size"] >= 2].sort_values("sharpe", ascending=False).head(10)
    print("\n=== TOP 10 by Sharpe (any size) ===\n")
    with pd.option_context("display.width", 220, "display.max_colwidth", 70):
        print(top_sh[cols].to_string(index=False))


if __name__ == "__main__":
    main()
