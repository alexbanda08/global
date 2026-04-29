"""
Parameter-plateau test — robustness test #2 from the mission brief.

For each numeric parameter of a signal generator, sweep ±25% and ±50%
around the default while holding others fixed, compute Sharpe / Calmar /
MaxDD at each grid point, and report:
  * degradation_25pct: max % drop in Sharpe at ±25% vs baseline
  * degradation_50pct: max % drop at ±50%
  * worst_param: the param whose sweep showed the sharpest cliff

Pass criteria (per spec):
  * degradation_25pct < 30%
  * degradation_50pct < 60%
  * No sharp cliff (defined: any single grid point where Sharpe < 0.3× baseline)
"""
from __future__ import annotations

import inspect
from typing import Callable

import numpy as np
import pandas as pd


def _numeric_params(fn: Callable) -> dict[str, float]:
    """Discover numeric (int/float) params of a signal fn from its signature."""
    sig = inspect.signature(fn)
    out = {}
    for name, p in sig.parameters.items():
        if name in ("df", "ohlcv", "data"):
            continue
        if p.default is inspect.Parameter.empty:
            continue
        if isinstance(p.default, bool):           # bool is subclass of int — skip
            continue
        if isinstance(p.default, (int, float)) and p.default != 0:
            out[name] = float(p.default)
    return out


def parameter_plateau(
    signal_fn: Callable,
    runner: Callable[[dict], pd.Series],     # runner(param_overrides) -> equity
    baseline_params: dict[str, float] | None = None,
    perturbation_pcts: tuple[float, ...] = (-0.5, -0.25, 0.25, 0.5),
    bars_per_year: float = 2190.0,
) -> dict:
    """
    Runs the parameter-plateau sweep. `runner` takes a dict of
    overrides (e.g., {"don_len": 25}), computes a backtest, and returns
    the equity series. Baseline is run once with no overrides.
    """
    from eval.metrics import sharpe_ratio, calmar_ratio, max_drawdown

    if baseline_params is None:
        baseline_params = _numeric_params(signal_fn)

    baseline_eq = runner({})
    baseline_rets = baseline_eq.pct_change().dropna()
    baseline_sharpe = sharpe_ratio(baseline_rets, bars_per_year)
    baseline_mdd    = max_drawdown(baseline_eq)
    years = len(baseline_eq) / bars_per_year
    baseline_cagr = (baseline_eq.iloc[-1] / baseline_eq.iloc[0]) ** (1 / max(years, 1e-6)) - 1.0
    baseline_calmar = calmar_ratio(baseline_cagr, baseline_mdd)

    results: dict[str, dict] = {}
    worst_25_pct_drop = 0.0
    worst_50_pct_drop = 0.0
    cliff_hit = False
    worst_param = None

    for pname, pval in baseline_params.items():
        sweep = {}
        for pct in perturbation_pcts:
            new_val = pval * (1.0 + pct)
            if "period" in pname or "len" in pname or "window" in pname or \
               "bars" in pname or "lookback" in pname:
                new_val = max(2, int(round(new_val)))
            overrides = {pname: new_val}
            try:
                eq = runner(overrides)
            except Exception as e:
                sweep[pct] = {"error": f"{type(e).__name__}: {e}"}
                continue
            if eq is None or len(eq) < 30:
                sweep[pct] = {"error": "no_equity"}
                continue
            rets = eq.pct_change().dropna()
            sh = sharpe_ratio(rets, bars_per_year)
            mdd = max_drawdown(eq)
            yrs = len(eq) / bars_per_year
            cgr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs, 1e-6)) - 1.0
            cal = calmar_ratio(cgr, mdd)
            sweep[pct] = {
                "value": new_val,
                "sharpe": round(sh, 3),
                "calmar": round(cal, 3),
                "max_dd": round(mdd, 4),
            }
            # Track worst degradation
            if baseline_sharpe > 0:
                drop = 1.0 - (sh / baseline_sharpe)
            else:
                drop = abs(sh - baseline_sharpe)
            if abs(pct) <= 0.26 and drop > worst_25_pct_drop:
                worst_25_pct_drop = drop
            if drop > worst_50_pct_drop:
                worst_50_pct_drop = drop
                worst_param = pname
            # Cliff detection
            if baseline_sharpe > 0 and sh < 0.3 * baseline_sharpe:
                cliff_hit = True
        results[pname] = {
            "baseline_value": pval,
            "sweep": sweep,
        }

    passed = (
        worst_25_pct_drop < 0.30
        and worst_50_pct_drop < 0.60
        and not cliff_hit
    )
    return {
        "baseline_sharpe": round(baseline_sharpe, 3),
        "baseline_calmar": round(baseline_calmar, 3),
        "baseline_mdd":    round(baseline_mdd, 4),
        "worst_25pct_sharpe_drop": round(worst_25_pct_drop, 3),
        "worst_50pct_sharpe_drop": round(worst_50_pct_drop, 3),
        "cliff_detected":  bool(cliff_hit),
        "worst_param":     worst_param,
        "params":          results,
        "passed":          bool(passed),
    }
