"""
Long-history portfolio ranker — excludes TON cells (Binance listing
2024-08) so the common window stays 2021-2026 (full 6 years).
Filters flat (zero-variance) equity curves automatically.

Writes:
  phase5_results/perps_portfolio_hunt_long.csv
  phase5_results/perps_portfolio_top_long.csv
  phase5_results/perps_correlation_matrix_long.csv
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "research" / "phase5_results"
EQ = OUT / "equity_curves" / "perps"

BPY = 365.25 * 6


def main():
    paths = sorted(EQ.glob("*.parquet"))
    curves: dict[str, pd.Series] = {}
    dropped = {"ton": [], "flat": [], "short_hist": []}

    for p in paths:
        label = p.stem
        # Exclude TON cells — their short history forces common-window truncation
        if "TON" in label.upper():
            dropped["ton"].append(label)
            continue
        eq = pd.read_parquet(p)["equity"]
        rets = eq.pct_change().dropna()
        # Drop flat / near-flat equity (SMC cells with 0 trades)
        if rets.std() < 1e-6 or (rets == 0).mean() > 0.99:
            dropped["flat"].append(label)
            continue
        # Need 2021 start for a fair 6-year window
        if eq.index[0].year > 2021:
            dropped["short_hist"].append(label)
            continue
        curves[label] = eq

    print(f"Pool after filters: {len(curves)} active cells")
    print(f"  Dropped (TON):        {len(dropped['ton'])}")
    print(f"  Dropped (flat SMC):   {len(dropped['flat'])}")
    print(f"  Dropped (short hist): {len(dropped['short_hist'])}")
    if dropped['short_hist']:
        print(f"    short: {', '.join(dropped['short_hist'])}")

    # Align to common index
    common = None
    for eq in curves.values():
        common = eq.index if common is None else common.intersection(eq.index)
    print(f"\nCommon window: {common[0].date()} -> {common[-1].date()}  ({len(common)} bars)")

    rets = pd.DataFrame({k: curves[k].reindex(common).pct_change().fillna(0)
                         for k in sorted(curves)})

    # Correlation matrix
    corr = rets.corr()
    corr.round(3).to_csv(OUT / "perps_correlation_matrix_long.csv")

    # Enumerate 2- and 3-sleeve blends (skip 4-sleeve for speed — rerun later if needed)
    all_rows = []
    labels = sorted(curves.keys())
    for size in (2, 3):     # 4-sleeve skipped for speed — 230k combos blew prior run
        combos = list(itertools.combinations(labels, size))
        print(f"Scoring {len(combos)} {size}-sleeve combos...")
        for combo in combos:
            sub = rets[list(combo)]
            port_rets = sub.mean(axis=1)
            port_eq = (1.0 + port_rets).cumprod()
            if len(port_eq) < 30:
                continue
            mu, sd = float(port_rets.mean()), float(port_rets.std())
            sh = (mu / sd) * np.sqrt(BPY) if sd > 0 else 0.0
            peak = port_eq.cummax()
            mdd = float((port_eq / peak - 1.0).min())
            yrs = (port_eq.index[-1] - port_eq.index[0]).total_seconds() / (365.25 * 86400)
            total = float(port_eq.iloc[-1] / port_eq.iloc[0] - 1)
            cagr = (1 + total) ** (1 / max(yrs, 1e-6)) - 1.0
            cal = cagr / abs(mdd) if mdd != 0 else 0.0
            yearly = {}
            pos = 0
            for yr in sorted(set(port_eq.index.year)):
                ye = port_eq[port_eq.index.year == yr]
                if len(ye) < 30:
                    continue
                r = float(ye.iloc[-1] / ye.iloc[0] - 1)
                yearly[yr] = r
                if r > 0:
                    pos += 1
            sub_corr = corr.loc[list(combo), list(combo)].values
            avg_corr = float(sub_corr[np.triu_indices(size, k=1)].mean())
            all_rows.append({
                "size": size,
                "sleeves": " + ".join(combo),
                "sharpe": round(sh, 3),
                "cagr": round(cagr, 4),
                "max_dd": round(mdd, 4),
                "calmar": round(cal, 3),
                "min_yr": round(min(yearly.values()) if yearly else 0, 4),
                "pos_yrs": pos,
                "n_yrs": len(yearly),
                "avg_pair_corr": round(avg_corr, 3),
            })

    df = pd.DataFrame(all_rows)
    df.to_csv(OUT / "perps_portfolio_hunt_long.csv", index=False)
    print(f"\nTotal combos: {len(df)}")

    # Only consider 6/6-year-positive portfolios — those are the promotion-grade ones
    six_of_six = df[df["pos_yrs"] == 6].sort_values(
        ["sharpe", "min_yr"], ascending=[False, False]
    ).head(30)
    six_of_six.to_csv(OUT / "perps_portfolio_top_long.csv", index=False)

    print(f"\nCombos with 6/6 positive years: {(df['pos_yrs'] == 6).sum()}")
    print("\n=== TOP 30 (6/6 years, sorted by Sharpe) ===\n")
    with pd.option_context("display.width", 220, "display.max_colwidth", 90):
        print(six_of_six.to_string(index=False))


if __name__ == "__main__":
    main()
