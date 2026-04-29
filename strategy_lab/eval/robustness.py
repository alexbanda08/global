"""
Phase 5.5 robustness battery — 4-of-5 tests (plateau deferred).

Tests:
  1. Per-year consistency      — Sharpe + win rate + return per calendar year
  2. Null permutation          — shuffle bar returns N times, compare strategy
                                 Sharpe dist on shuffled data vs real
  3. Block bootstrap           — stationary-bootstrap trade returns; 95% CI
                                 on Sharpe / Calmar / MDD
  4. Walk-forward efficiency   — 6 anchored expanding-window folds

Parameter-plateau test (mission item 2) is deferred to a separate module
since it requires per-strategy param-space maps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from eval.metrics import (
    sharpe_ratio, calmar_ratio, max_drawdown,
)


@dataclass
class RobustnessReport:
    strategy_id: str
    symbol: str
    tf: str
    per_year: dict[int, dict[str, float]]            = field(default_factory=dict)
    permutation: dict[str, float]                    = field(default_factory=dict)
    bootstrap: dict[str, dict[str, float]]           = field(default_factory=dict)
    walk_forward: dict[str, Any]                     = field(default_factory=dict)

    def verdict(self) -> dict:
        """Compact pass/fail summary of the battery."""
        pf = {}
        # per-year: positive Sharpe in >=70% of years
        years = list(self.per_year.values())
        if years:
            pos = sum(1 for y in years if y.get("sharpe", 0) > 0)
            pf["per_year_consistency"] = pos / len(years) >= 0.70
        # permutation: p < 0.01
        pf["permutation_p<0.01"] = self.permutation.get("p_value", 1.0) < 0.01
        # bootstrap: Sharpe lower CI > 0.5
        bs = self.bootstrap
        pf["bootstrap_sharpe_lowerCI>0.5"] = bs.get("sharpe", {}).get("ci_lo", 0.0) > 0.5
        pf["bootstrap_calmar_lowerCI>1.0"] = bs.get("calmar", {}).get("ci_lo", 0.0) > 1.0
        pf["bootstrap_mdd_upperCI<30%"] = bs.get("max_dd", {}).get("ci_hi", 0.0) > -0.30
        # WFE: ratio >= 0.5
        wf = self.walk_forward
        pf["walk_forward_efficiency>0.5"] = wf.get("efficiency_ratio", 0.0) >= 0.5
        pf["walk_forward_pos_folds>=5"] = wf.get("n_positive_folds", 0) >= 5
        pf["tests_passed"] = sum(1 for v in pf.values() if v is True)
        pf["tests_total"]  = sum(1 for v in pf.values() if isinstance(v, bool))
        return pf


# ---------------------------------------------------------------------
# 1. Per-year breakdown
# ---------------------------------------------------------------------
def per_year_stats(equity: pd.Series, bars_per_year: float) -> dict[int, dict[str, float]]:
    if equity is None or len(equity) < 2:
        return {}
    out: dict[int, dict[str, float]] = {}
    for yr in sorted(set(equity.index.year)):
        eq_y = equity[equity.index.year == yr]
        if len(eq_y) < 30:
            continue
        rets = eq_y.pct_change().dropna()
        sh = sharpe_ratio(rets, bars_per_year)
        peak = eq_y.cummax()
        dd = (eq_y / peak - 1.0).min()
        total = eq_y.iloc[-1] / eq_y.iloc[0] - 1.0
        out[int(yr)] = {
            "sharpe":      round(sh, 3),
            "return":      round(float(total), 4),
            "max_dd":      round(float(dd), 4),
            "n_bars":      int(len(eq_y)),
        }
    return out


# ---------------------------------------------------------------------
# 3. Block-bootstrap CIs on Sharpe / Calmar / MaxDD
#    Politis-Romano stationary bootstrap with expected-block-length p.
# ---------------------------------------------------------------------
def block_bootstrap_ci(
    returns: pd.Series,
    n_iter: int = 1000,
    block_prob: float = 0.1,          # 1/p = expected block length (10 bars default)
    bars_per_year: float = 2190.0,
    seed: int = 42,
) -> dict[str, dict[str, float]]:
    if returns is None or len(returns) < 60:
        return {}
    r = returns.to_numpy()
    n = len(r)
    rng = np.random.default_rng(seed)

    sharpes = np.empty(n_iter)
    calmars = np.empty(n_iter)
    mdds    = np.empty(n_iter)

    for k in range(n_iter):
        # stationary bootstrap sample of length n
        idxs = np.empty(n, dtype=np.int64)
        i = 0
        while i < n:
            start = rng.integers(0, n)
            block_len = rng.geometric(block_prob)
            for b in range(block_len):
                if i >= n:
                    break
                idxs[i] = (start + b) % n
                i += 1
        sample = r[idxs]
        # reconstruct equity from returns
        eq = np.cumprod(1.0 + sample)
        ret_s = pd.Series(sample)
        sharpes[k] = sharpe_ratio(ret_s, bars_per_year)
        eq_s = pd.Series(eq)
        dd = float((eq_s / eq_s.cummax() - 1.0).min())
        mdds[k] = dd
        years = n / bars_per_year
        cagr = eq[-1] ** (1.0 / max(years, 1e-6)) - 1.0 if years > 0 else 0.0
        calmars[k] = calmar_ratio(cagr, dd)

    def _ci(arr, name):
        return {
            "mean":  round(float(np.mean(arr)), 4),
            "ci_lo": round(float(np.quantile(arr, 0.025)), 4),
            "ci_hi": round(float(np.quantile(arr, 0.975)), 4),
        }
    return {
        "sharpe": _ci(sharpes, "sharpe"),
        "calmar": _ci(calmars, "calmar"),
        "max_dd": _ci(mdds,    "max_dd"),
    }


# ---------------------------------------------------------------------
# 2. Null / permutation test
#    Shuffle bar log-returns N times and rerun the strategy on each
#    shuffled price series. If real Sharpe > 99th percentile of null,
#    temporal edge is likely real.
# ---------------------------------------------------------------------
def permutation_test(
    df: pd.DataFrame,
    runner_on_df: Callable[[pd.DataFrame], pd.Series],   # returns equity
    n_perm: int = 30,
    bars_per_year: float = 2190.0,
    seed: int = 42,
) -> dict[str, float]:
    """
    `runner_on_df(df)` must take an OHLCV DataFrame and return the
    strategy's equity series for that DataFrame. We call it on the real
    df AND on n_perm shuffled versions.
    """
    real_eq = runner_on_df(df)
    if real_eq is None or len(real_eq) < 30:
        return {"error": "no_real_equity"}
    real_sharpe = sharpe_ratio(real_eq.pct_change().dropna(), bars_per_year)

    rng = np.random.default_rng(seed)
    close = df["close"].to_numpy()
    log_r = np.diff(np.log(close))
    null_sharpes = []
    for k in range(n_perm):
        perm = rng.permutation(log_r)
        new_close = np.exp(np.concatenate([[np.log(close[0])], np.cumsum(perm) + np.log(close[0])]))
        df_perm = df.copy()
        # Shift high/low proportionally to match new close path.
        scale = new_close / close
        df_perm["close"] = new_close
        df_perm["open"]  = df["open"].to_numpy()  * scale
        df_perm["high"]  = df["high"].to_numpy()  * scale
        df_perm["low"]   = df["low"].to_numpy()   * scale
        try:
            eq_perm = runner_on_df(df_perm)
            if eq_perm is not None and len(eq_perm) >= 30:
                null_sharpes.append(
                    sharpe_ratio(eq_perm.pct_change().dropna(), bars_per_year)
                )
        except Exception:
            continue

    null_arr = np.asarray(null_sharpes, dtype=float)
    if len(null_arr) < 5:
        return {"error": "too_few_successful_permutations", "n_permutations_run": len(null_arr)}
    p = float((null_arr >= real_sharpe).mean())
    return {
        "n_permutations":  int(len(null_arr)),
        "real_sharpe":     round(real_sharpe, 3),
        "null_mean":       round(float(null_arr.mean()), 3),
        "null_99th":       round(float(np.quantile(null_arr, 0.99)), 3),
        "p_value":         round(p, 4),
    }


# ---------------------------------------------------------------------
# 4. Walk-forward efficiency — 6 anchored expanding folds
# ---------------------------------------------------------------------
def walk_forward_efficiency(
    equity: pd.Series,
    bars_per_year: float = 2190.0,
    n_folds: int = 6,
) -> dict[str, Any]:
    if equity is None or len(equity) < 6 * 30:
        return {"error": "insufficient_data"}
    # Split equity OOS windows: first IS fold is bars [0 .. n/7 * 2], then
    # each subsequent OOS window is size n/7.
    total = len(equity)
    fold_size = total // (n_folds + 1)
    fold_reports = []
    is_sharpes: list[float] = []
    oos_sharpes: list[float] = []

    for k in range(n_folds):
        is_start = 0
        is_end   = fold_size * (k + 1)
        oos_end  = fold_size * (k + 2)
        is_eq  = equity.iloc[is_start:is_end]
        oos_eq = equity.iloc[is_end:oos_end]
        if len(is_eq) < 30 or len(oos_eq) < 30:
            continue
        is_sh  = sharpe_ratio(is_eq.pct_change().dropna(),  bars_per_year)
        oos_sh = sharpe_ratio(oos_eq.pct_change().dropna(), bars_per_year)
        is_sharpes.append(is_sh)
        oos_sharpes.append(oos_sh)
        fold_reports.append({
            "fold":       k + 1,
            "is_sharpe":  round(is_sh, 3),
            "oos_sharpe": round(oos_sh, 3),
        })

    if not is_sharpes:
        return {"error": "no_valid_folds"}
    avg_is  = float(np.mean(is_sharpes))
    avg_oos = float(np.mean(oos_sharpes))
    eff = avg_oos / avg_is if avg_is != 0 else 0.0
    return {
        "n_folds":         len(fold_reports),
        "avg_is_sharpe":   round(avg_is, 3),
        "avg_oos_sharpe":  round(avg_oos, 3),
        "efficiency_ratio": round(eff, 3),
        "n_positive_folds": int(sum(1 for s in oos_sharpes if s > 0)),
        "worst_fold_sharpe": round(float(min(oos_sharpes)), 3),
        "folds":           fold_reports,
    }


# ---------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------
def run_robustness(
    strategy_id: str, symbol: str, tf: str,
    equity: pd.Series,
    runner_on_df: Callable[[pd.DataFrame], pd.Series] | None,
    df: pd.DataFrame | None,
    bars_per_year: float = 2190.0,
    n_perm: int = 30,
    n_bootstrap: int = 1000,
) -> RobustnessReport:
    report = RobustnessReport(strategy_id=strategy_id, symbol=symbol, tf=tf)
    report.per_year = per_year_stats(equity, bars_per_year)

    rets = equity.pct_change().dropna()
    report.bootstrap = block_bootstrap_ci(
        rets, n_iter=n_bootstrap, bars_per_year=bars_per_year,
    )

    if runner_on_df is not None and df is not None and n_perm > 0:
        try:
            report.permutation = permutation_test(
                df, runner_on_df, n_perm=n_perm, bars_per_year=bars_per_year,
            )
        except Exception as e:
            report.permutation = {"error": f"{type(e).__name__}: {e}"}

    report.walk_forward = walk_forward_efficiency(equity, bars_per_year=bars_per_year)
    return report
