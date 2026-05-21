"""Replay our policy comparison FILTERED TO WALLET'S ACTUAL ENTRY CONDITIONS.

Hypothesis: our scanner's all-negative result is from the maker-fee bug
narrowing entries to sum_asks > $1.035, which selects asymmetric markets
with bad partial-fill economics.

Test: re-run policy comparison restricted to sum_asks ∈ [1.005, 1.020]
(matching the 85% mode of all 4 decoded wallets' fires). Do HOLD economics
flip positive?

Reads existing policy_compare.parquet (already computed in previous run),
filters, re-aggregates.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))
from fees import poly_maker_rebate_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS
FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)

# Wallet-observed entry condition
SUM_LO = 1.005
SUM_HI = 1.020


def recompute_with_correct_rebate(df: pd.DataFrame, notional: float) -> pd.DataFrame:
    """The existing policy_compare.parquet was computed with the correct
    fee model (poly_maker_rebate_per_share), so we can use those PnL cols
    directly. But validate by recomputing PURE-fill PnL with rebate-as-income.
    """
    n = notional
    df = df.copy()
    # Sanity-check pnl_hold for BOTH events:
    # pnl = n × (ask_up + ask_dn) + n × (reb_up + reb_dn) - n
    df["expected_pnl_BOTH"] = np.where(
        df.scenario == "BOTH",
        n * (df.ask_up + df.ask_dn) - n
        + n * df.ask_up.apply(lambda p: poly_maker_rebate_per_share(p, FEE_RATE))
        + n * df.ask_dn.apply(lambda p: poly_maker_rebate_per_share(p, FEE_RATE)),
        np.nan,
    )
    return df


def analyze_cell(cell: str, notional: float = 200.0, window_days: float = 21.0):
    p = ROOT / "data" / "v4" / "canonical" / "_results" / f"mint_and_sell_{cell}_2026_05_16" / "policy_compare.parquet"
    if not p.exists():
        print(f"SKIP {cell}: no policy_compare.parquet")
        return None
    df = pd.read_parquet(p)
    n_all = len(df)
    df = recompute_with_correct_rebate(df, notional)

    # Filter to wallet conditions
    in_band = df[(df.sum_asks >= SUM_LO) & (df.sum_asks <= SUM_HI)].copy()
    n_band = len(in_band)
    if n_band == 0:
        print(f"{cell}: 0 fires in [{SUM_LO}, {SUM_HI}] (n_all={n_all})")
        return None

    pct_band = 100 * n_band / n_all
    pct_both = 100 * (in_band.scenario == "BOTH").mean()
    pct_one = 100 * in_band.scenario.isin(["Up_HELD", "Down_HELD"]).mean()
    partial = in_band[in_band.scenario.isin(["Up_HELD", "Down_HELD"])]
    held_wr = partial.held_won.mean() if len(partial) else float("nan")

    # PnL per policy in this band
    out = dict(
        cell=cell, n_band=n_band, pct_of_all=pct_band,
        pct_both=pct_both, pct_one=pct_one, held_wr=held_wr,
    )
    for pol in ("hold", "market_exit", "hybrid"):
        col = f"pnl_{pol}"
        out[f"mean_{pol}"] = float(in_band[col].mean())
        out[f"total_{pol}"] = float(in_band[col].sum())
        out[f"per_day_{pol}"] = float(in_band[col].sum()) / window_days

    return out


def main():
    cells = ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"]
    rows = []
    for c in cells:
        r = analyze_cell(c)
        if r:
            rows.append(r)
    df = pd.DataFrame(rows)
    print(f"\n=== Filtered to wallet's entry conditions: sum_asks ∈ [{SUM_LO}, {SUM_HI}] ===")
    print(f"  notional=$200, window=21d\n")
    print(f"  {'Cell':<10} {'n_band':>7} {'%all':>6} {'%BOTH':>7} {'%ONE':>7} {'held_WR':>8} {'HOLD/op':>9} {'MKT/op':>9} {'HYB/op':>9}")
    for r in rows:
        hwr = f"{r['held_wr']*100:.1f}%" if not np.isnan(r['held_wr']) else "  N/A"
        print(f"  {r['cell']:<10} {r['n_band']:>7} {r['pct_of_all']:>5.1f}% {r['pct_both']:>6.1f}% {r['pct_one']:>6.1f}% {hwr:>8} "
              f"${r['mean_hold']:>7.4f} ${r['mean_market_exit']:>7.4f} ${r['mean_hybrid']:>7.4f}")

    print()
    print(f"  {'Cell':<10} {'HOLD $/day':>12} {'MKT $/day':>12} {'HYB $/day':>12}")
    for r in rows:
        print(f"  {r['cell']:<10} ${r['per_day_hold']:>10.2f} ${r['per_day_market_exit']:>10.2f} ${r['per_day_hybrid']:>10.2f}")

    print(f"\n  CONSOLIDATED:")
    print(f"    HOLD       total=${sum(r['total_hold'] for r in rows):,.2f}   $/day(sample)=${sum(r['per_day_hold'] for r in rows):,.2f}")
    print(f"    MARKET_EXIT total=${sum(r['total_market_exit'] for r in rows):,.2f}   $/day(sample)=${sum(r['per_day_market_exit'] for r in rows):,.2f}")
    print(f"    HYBRID     total=${sum(r['total_hybrid'] for r in rows):,.2f}   $/day(sample)=${sum(r['per_day_hybrid'] for r in rows):,.2f}")


if __name__ == "__main__":
    main()
