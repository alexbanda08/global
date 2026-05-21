"""Validation gates for the F2 follow strategy.

Strategy (final): binance-momentum FOLLOW in last 60s of slug.

Best threshold combo from sweep:
  - max_asz >= 1000 (deep maker quote)
  - |binance_ret_60s| >= 2 bp
  - offset >= 240s (last minute of 5m slug)
  - Direction: SAME as sign(binance_ret_60s)
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cyclops.validate.permutation import permutation_test
from cyclops.validate.bootstrap import bootstrap_mean_ci
from cyclops.validate.walkforward import walkforward_test


def filter_to_best(df: pd.DataFrame) -> pd.DataFrame:
    """Apply best-threshold filter to the FOLLOW dataset."""
    df = df.copy()
    if "abs_ret_bp" not in df.columns:
        df["abs_ret_bp"] = df["binance_ret_60s"].abs() * 10000
    mask = (
        (df["max_asz"] >= 1000)
        & (df["abs_ret_bp"] >= 2.0)
        & (df["offset_s"] >= 240)
    )
    return df[mask].copy()


def main():
    df = pd.read_csv("strategy_lab/f2_replica/_results/f2_follow.csv")
    print(f"loaded follow CSV: n={len(df)}")
    sub = filter_to_best(df)
    n = len(sub)
    wr = sub["won"].mean()
    mean_pnl = sub["pnl_usd"].mean()
    sum_pnl = sub["pnl_usd"].sum()
    mean_entry = sub["entry_px"].mean()
    print(f"\nbest config: max_asz>=1000 AND |ret_60s|>=2bp AND offset>=240s")
    print(f"  n_trades  : {n}")
    print(f"  WR        : {wr*100:.2f}%")
    print(f"  breakeven : {mean_entry*100:.2f}% (mean entry)")
    print(f"  edge      : {(wr-mean_entry)*100:+.2f}pp")
    print(f"  mean PnL  : ${mean_pnl:+.4f}  (stake=$1)")
    print(f"  total PnL : ${sum_pnl:+.2f}")
    print(f"  total @$25 stake: ${sum_pnl*25:+.2f}")

    # G3 permutation
    print()
    print("=" * 70)
    print("G3 — permutation test (5000 outcome shuffles)")
    print("=" * 70)
    perm = permutation_test(sub, n_permutations=5000, seed=42)
    p = perm["p_value"]
    print(f"  observed mean PnL: ${perm['observed_mean_pnl']:+.4f}")
    print(f"  null mean PnL:     ${perm['null_mean']:+.4f}")
    print(f"  null std:          ${perm['null_std']:.4f}")
    print(f"  null 95th pct:     ${perm['null_q95']:+.4f}")
    print(f"  p-value:           {p:.4f}")
    print(f"  verdict: G3 {'PASS' if p < 0.05 else 'FAIL'}")

    # G4 bootstrap
    print()
    print("=" * 70)
    print("G4 — bootstrap 95% CI (20000 resamples)")
    print("=" * 70)
    boot = bootstrap_mean_ci(sub, n_boot=20000, seed=42)
    lo, hi = boot["ci_lower"], boot["ci_upper"]
    print(f"  observed mean: ${boot['observed_mean_pnl']:+.4f}")
    print(f"  95% CI: ${lo:+.4f} .. ${hi:+.4f}")
    print(f"  P(mean ≤ 0): {boot['frac_negative_draws']*100:.2f}%")
    print(f"  verdict: G4 {'PASS' if lo > 0 else 'FAIL'}")

    # G2 walkforward
    print()
    print("=" * 70)
    print("G2 — walkforward (5d train / 2d test)")
    print("=" * 70)
    wf = walkforward_test(sub, train_days=5, test_days=2)
    print(f"  n_windows  : {wf['n_windows']}")
    print(f"  n_positive : {wf['n_positive']}")
    print(f"  frac_positive: {wf['frac_positive']:.3f}")
    print(f"  verdict    : G2 {wf['verdict']}")
    for w in wf["windows"]:
        marker = "+" if w["mean_pnl"] > 0 else "-"
        print(f"    [{marker}] day {w['test_start_day']}-{w['test_end_day']}  "
              f"n={w['n_trades']:3d}  mean=${w['mean_pnl']:+.4f}  "
              f"total=${w['total_pnl']:+.2f}")

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    gates = [
        ("G1 mean PnL > 0", mean_pnl > 0),
        ("G3 perm p < 0.05", p < 0.05),
        ("G4 bootstrap CI lo > 0", lo > 0),
        ("G2 walkforward ≥6/8", wf["verdict"] == "PASS"),
    ]
    for label, ok in gates:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")


if __name__ == "__main__":
    main()
