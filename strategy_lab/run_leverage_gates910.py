"""
Gates 9 (trade-order shuffle MC) and 10 (forward path simulation MC).

Gate 9 — Trade-order / path-shuffle Monte Carlo (10,000 iters):
  Bootstrap daily returns WITH REPLACEMENT (iid), rebuild equity per sample,
  compute MDD / total_return / time_to_recovery distributions.
  Gate 9 PASS if: 95th percentile worst-MDD > -30%
                  (even in worst-5%-of-orderings, DD survives)

Gate 10 — Forward-path Monte Carlo (1,000 paths x 1 year):
  Sample 1-year forward paths of 2190 bars from empirical return distribution.
  Gate 10 PASS if: 95th percentile worst-1y-MDD > -25%
                   AND median 1y CAGR > 15%
                  (gives deployment kill-switch sizing + realistic 1y forecast)

Outputs: docs/research/phase5_results/leverage_gates910_results.json
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.run_leverage_study import SLEEVE_SPECS, PORTFOLIOS, sleeve_data, OUT, BPY
from strategy_lab.run_leverage_study_v2 import simulate_lev
from strategy_lab.run_leverage_audit import (
    build_p3_invvol, build_p5_btc_defensive, eqw_blend, invvol_blend,
)

# =============================================================================
# Build the three candidate blends
# =============================================================================
def build_candidates() -> dict[str, pd.Series]:
    print("Building candidate equity curves...")
    # Warm caches
    for s in SLEEVE_SPECS:
        sleeve_data(s)
    # P3_invvol
    p3_base_curves = build_p3_invvol()
    p3_eq = invvol_blend(p3_base_curves, window=500)
    # P5_btc_defensive
    p5_def_curves = build_p5_btc_defensive()
    p5_eq = eqw_blend(p5_def_curves)
    # NEW 60/40
    idx = p3_eq.index.intersection(p5_eq.index)
    combined_r = (0.60 * p3_eq.reindex(idx).pct_change().fillna(0)
                 + 0.40 * p5_eq.reindex(idx).pct_change().fillna(0))
    combo_eq = (1 + combined_r).cumprod() * 10_000.0
    return {
        "NEW_60_40":        combo_eq,
        "P3_invvol":        p3_eq,
        "P5_btc_defensive": p5_eq,
    }

# =============================================================================
# Gate 9: Trade-order / path-shuffle Monte Carlo
# =============================================================================
def gate9_path_shuffle(eq: pd.Series, n_iter: int = 10_000, seed: int = 42) -> dict:
    """
    Bootstrap daily returns with replacement (iid), rebuild equity per sample.
    Returns percentile distribution of MDD, total_return, time_to_recovery.
    """
    rets = eq.pct_change().dropna().to_numpy()
    n = len(rets)
    rng = np.random.default_rng(seed)
    mdds = np.empty(n_iter)
    total_rets = np.empty(n_iter)
    recovery_bars = np.full(n_iter, -1, dtype=int)  # -1 = never recovered from worst DD

    for k in range(n_iter):
        sampled = rng.choice(rets, size=n, replace=True)
        eq_path = np.cumprod(1 + sampled)
        peak = np.maximum.accumulate(eq_path)
        dd = eq_path / peak - 1.0
        mdds[k] = dd.min()
        total_rets[k] = eq_path[-1] - 1.0
        # time to recovery after deepest DD
        worst_idx = int(np.argmin(dd))
        worst_peak = peak[worst_idx]
        post = eq_path[worst_idx:]
        recovered = np.where(post >= worst_peak)[0]
        recovery_bars[k] = recovered[0] if len(recovered) > 0 else -1

    mdd_p5  = float(np.percentile(mdds, 5))
    mdd_p50 = float(np.percentile(mdds, 50))
    mdd_p95 = float(np.percentile(mdds, 95))
    ret_p5  = float(np.percentile(total_rets, 5))
    ret_p50 = float(np.percentile(total_rets, 50))
    ret_p95 = float(np.percentile(total_rets, 95))

    valid_recov = recovery_bars[recovery_bars >= 0]
    recov_p50 = float(np.percentile(valid_recov, 50)) if len(valid_recov) else -1
    recov_p95 = float(np.percentile(valid_recov, 95)) if len(valid_recov) else -1
    never_pct = float((recovery_bars == -1).mean() * 100)

    # Gate: worst 5% MDD > -30%
    worst5_mdd = mdd_p5  # p5 is the worst-5% (most negative)
    passes = worst5_mdd > -0.30

    return {
        "n_iter": n_iter,
        "observed_mdd": round(float((eq / eq.cummax() - 1).min()), 4),
        "observed_total_return": round(float(eq.iloc[-1]/eq.iloc[0] - 1), 4),
        "mdd_p5":   round(mdd_p5, 4),
        "mdd_p50":  round(mdd_p50, 4),
        "mdd_p95":  round(mdd_p95, 4),
        "ret_p5":   round(ret_p5, 4),
        "ret_p50":  round(ret_p50, 4),
        "ret_p95":  round(ret_p95, 4),
        "recovery_bars_p50": round(recov_p50, 1),
        "recovery_bars_p95": round(recov_p95, 1),
        "never_recovered_pct": round(never_pct, 2),
        "gate9_pass": passes,
    }

# =============================================================================
# Gate 10: Forward-path Monte Carlo (1-year simulated futures)
# =============================================================================
def gate10_forward_paths(eq: pd.Series, n_paths: int = 1000,
                         year_bars: int = 2190, seed: int = 42) -> dict:
    """
    Sample 1-year forward paths from empirical return distribution.
    Returns percentile distribution of 1yr DD, 1yr CAGR.
    """
    rets = eq.pct_change().dropna().to_numpy()
    rng = np.random.default_rng(seed)
    year_mdds = np.empty(n_paths)
    year_cagrs = np.empty(n_paths)
    for k in range(n_paths):
        sampled = rng.choice(rets, size=year_bars, replace=True)
        path = np.cumprod(1 + sampled)
        peak = np.maximum.accumulate(path)
        dd = path / peak - 1.0
        year_mdds[k] = dd.min()
        year_cagrs[k] = path[-1] - 1.0  # ~1y CAGR since length == 1yr

    mdd_p5   = float(np.percentile(year_mdds, 5))
    mdd_p25  = float(np.percentile(year_mdds, 25))
    mdd_p50  = float(np.percentile(year_mdds, 50))
    mdd_p95  = float(np.percentile(year_mdds, 95))
    cagr_p5  = float(np.percentile(year_cagrs, 5))
    cagr_p25 = float(np.percentile(year_cagrs, 25))
    cagr_p50 = float(np.percentile(year_cagrs, 50))
    cagr_p95 = float(np.percentile(year_cagrs, 95))
    p_neg_year = float((year_cagrs < 0).mean() * 100)
    p_dd_20 = float((year_mdds < -0.20).mean() * 100)
    p_dd_30 = float((year_mdds < -0.30).mean() * 100)

    passes_mdd = mdd_p5 > -0.25
    passes_median_cagr = cagr_p50 > 0.15
    passes = passes_mdd and passes_median_cagr

    return {
        "n_paths": n_paths,
        "year_bars": year_bars,
        "mdd_p5":   round(mdd_p5, 4),
        "mdd_p25":  round(mdd_p25, 4),
        "mdd_p50":  round(mdd_p50, 4),
        "mdd_p95":  round(mdd_p95, 4),
        "cagr_p5":  round(cagr_p5, 4),
        "cagr_p25": round(cagr_p25, 4),
        "cagr_p50": round(cagr_p50, 4),
        "cagr_p95": round(cagr_p95, 4),
        "p_negative_year_pct":  round(p_neg_year, 2),
        "p_dd_worse_than_20pct":  round(p_dd_20, 2),
        "p_dd_worse_than_30pct":  round(p_dd_30, 2),
        "gate10_mdd_p5_gt_neg25":    passes_mdd,
        "gate10_median_cagr_gt_15":  passes_median_cagr,
        "gate10_pass": passes,
    }

# =============================================================================
# MAIN
# =============================================================================
def main():
    t0 = time.time()
    candidates = build_candidates()

    results: dict = {}
    for name, eq in candidates.items():
        print(f"\n=== {name} ===")
        print(f"  Gate 9: path-shuffle MC (n=10000)...")
        g9 = gate9_path_shuffle(eq, n_iter=10_000)
        print(f"    MDD 5th pct (worst 5%)  = {g9['mdd_p5']*100:.1f}%")
        print(f"    MDD 50th pct (median)   = {g9['mdd_p50']*100:.1f}%")
        print(f"    Total-ret 5th pct       = {g9['ret_p5']*100:.1f}%")
        print(f"    Total-ret median        = {g9['ret_p50']*100:.1f}%")
        print(f"    Never-recovered %       = {g9['never_recovered_pct']}%")
        print(f"    GATE 9 (worst-5% MDD > -30%): {'PASS' if g9['gate9_pass'] else 'FAIL'}")

        print(f"  Gate 10: forward 1-year path MC (n=1000)...")
        g10 = gate10_forward_paths(eq, n_paths=1000, year_bars=2190)
        print(f"    1y MDD 5th pct          = {g10['mdd_p5']*100:.1f}%")
        print(f"    1y MDD median           = {g10['mdd_p50']*100:.1f}%")
        print(f"    1y CAGR 5th pct         = {g10['cagr_p5']*100:.1f}%")
        print(f"    1y CAGR median          = {g10['cagr_p50']*100:.1f}%")
        print(f"    P(negative year)        = {g10['p_negative_year_pct']}%")
        print(f"    P(DD > 20%)             = {g10['p_dd_worse_than_20pct']}%")
        print(f"    P(DD > 30%)             = {g10['p_dd_worse_than_30pct']}%")
        print(f"    GATE 10 (5th%ile MDD > -25% AND median CAGR > 15%): "
              f"{'PASS' if g10['gate10_pass'] else 'FAIL'}")
        results[name] = {"gate9_path_shuffle": g9, "gate10_forward_paths": g10}

    out_path = OUT / "leverage_gates910_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("GATES 9 & 10 FINAL VERDICT")
    print("=" * 70)
    for name in candidates:
        g9 = results[name]["gate9_path_shuffle"]
        g10 = results[name]["gate10_forward_paths"]
        v9 = "PASS" if g9["gate9_pass"] else "FAIL"
        v10 = "PASS" if g10["gate10_pass"] else "FAIL"
        print(f"  {name:20s}  Gate9={v9}  Gate10={v10}")

    print(f"\nSaved -> {out_path}")
    print(f"Total runtime: {time.time() - t0:.1f}s")

if __name__ == "__main__":
    main()
