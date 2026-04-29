"""
Evaluation metrics for Phase 5 backtest matrix.

Each function takes minimal inputs (returns or equity series) so they can
be applied uniformly whether the engine ran v1, market, or limit mode.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# Classical ratios
# ---------------------------------------------------------------------
def sharpe_ratio(returns: pd.Series, periods_per_year: float) -> float:
    if returns is None or len(returns) < 2:
        return 0.0
    mu = float(returns.mean())
    sd = float(returns.std())
    return (mu / sd) * np.sqrt(periods_per_year) if sd > 0 else 0.0


def sortino_ratio(returns: pd.Series, periods_per_year: float) -> float:
    if returns is None or len(returns) < 2:
        return 0.0
    mu = float(returns.mean())
    dn = returns[returns < 0]
    if len(dn) < 2:
        return 0.0
    sd_dn = float(dn.std())
    return (mu / sd_dn) * np.sqrt(periods_per_year) if sd_dn > 0 else 0.0


def calmar_ratio(cagr: float, max_dd: float) -> float:
    return float(cagr / abs(max_dd)) if max_dd != 0 else 0.0


# ---------------------------------------------------------------------
# Drawdown primitives
# ---------------------------------------------------------------------
def max_drawdown(equity: pd.Series) -> float:
    if equity is None or len(equity) < 2:
        return 0.0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def dd_duration_bars(equity: pd.Series) -> int:
    """Longest peak-to-peak drawdown in bars."""
    if equity is None or len(equity) < 2:
        return 0
    peak = equity.cummax()
    in_dd = (equity < peak).astype(int)
    # run-length encoding of True spells
    longest = 0
    current = 0
    for v in in_dd.values:
        if v:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def dd_recovery_bars(equity: pd.Series) -> int:
    """Bars to recover from the deepest drawdown."""
    if equity is None or len(equity) < 2:
        return 0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    trough_idx = dd.idxmin()
    if pd.isna(trough_idx):
        return 0
    peak_at_trough = peak.loc[trough_idx]
    after_trough = equity.loc[trough_idx:]
    recovered = after_trough[after_trough >= peak_at_trough]
    if len(recovered) == 0:
        return len(after_trough)  # never recovered by end of sample
    first_recover = recovered.index[0]
    return int(equity.index.get_loc(first_recover) - equity.index.get_loc(trough_idx))


def ulcer_index(equity: pd.Series) -> float:
    """sqrt(mean(drawdown%^2)) — Martin 1987."""
    if equity is None or len(equity) < 2:
        return 0.0
    peak = equity.cummax()
    dd_pct = ((equity / peak) - 1.0) * 100.0
    return float(np.sqrt((dd_pct ** 2).mean()))


def ulcer_performance_index(
    equity: pd.Series, periods_per_year: float, rf: float = 0.0,
) -> float:
    if equity is None or len(equity) < 2:
        return 0.0
    total = float(equity.iloc[-1] / equity.iloc[0]) - 1.0
    years = len(equity) / periods_per_year
    cagr = (1 + total) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    ui = ulcer_index(equity)
    return (cagr - rf) / ui if ui > 0 else 0.0


# ---------------------------------------------------------------------
# Tail ratio
# ---------------------------------------------------------------------
def tail_ratio(returns: pd.Series, upper: float = 0.95, lower: float = 0.05) -> float:
    if returns is None or len(returns) < 20:
        return 0.0
    q_up = float(returns.quantile(upper))
    q_dn = float(returns.quantile(lower))
    return abs(q_up) / abs(q_dn) if q_dn != 0 else 0.0


# ---------------------------------------------------------------------
# Probabilistic Sharpe (Bailey & López de Prado 2012)
# Deflated Sharpe    (Bailey & López de Prado 2014)
# ---------------------------------------------------------------------
def probabilistic_sharpe(
    sharpe: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0,
    bench_sharpe: float = 0.0,
) -> float:
    """
    Returns P(true Sharpe > bench_sharpe | observed sharpe, n_obs, skew, kurt).
    Uses Gaussian CDF approximation.
    """
    try:
        from scipy.stats import norm
    except ImportError:
        return float("nan")
    if n_obs < 2:
        return 0.5
    denom = 1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe * sharpe
    if denom <= 0:
        return 0.5
    z = (sharpe - bench_sharpe) * np.sqrt(n_obs - 1) / np.sqrt(denom)
    return float(norm.cdf(z))


def deflated_sharpe(
    sharpe: float, n_obs: int, n_trials: int,
    sd_sharpe_trials: float | None = None,
    skew: float = 0.0, kurt: float = 3.0,
) -> float:
    """
    DSR = PSR with bench_sharpe = E[max(N trial Sharpes)] under null.
    Uses the asymptotic extreme-value approximation for iid normal Sharpes.
    `sd_sharpe_trials` is the std-dev of observed trial Sharpes — if None,
    assumes 1.0 (most conservative).
    """
    try:
        from scipy.stats import norm
    except ImportError:
        return float("nan")
    if n_trials <= 1:
        return probabilistic_sharpe(sharpe, n_obs, skew, kurt, 0.0)
    gamma = 0.5772156649  # Euler-Mascheroni
    emax = (
        (1.0 - gamma) * norm.ppf(1.0 - 1.0 / n_trials)
        + gamma * norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    )
    sd = sd_sharpe_trials if sd_sharpe_trials is not None else 1.0
    bench = emax * sd
    return probabilistic_sharpe(sharpe, n_obs, skew, kurt, bench)


# ---------------------------------------------------------------------
# Regime-conditional performance
# ---------------------------------------------------------------------
def regime_conditional_sharpe(
    returns: pd.Series, labels: pd.Series, periods_per_year: float,
) -> dict[str, float]:
    """
    Per-regime-label Sharpe. Returns a dict {label: sharpe}. Labels with
    fewer than 30 bars are skipped.
    """
    if returns is None or labels is None:
        return {}
    aligned = returns.reindex(labels.index).dropna()
    l = labels.reindex(aligned.index).astype(str)
    out: dict[str, float] = {}
    for lbl in l.unique():
        r = aligned[l == lbl]
        if len(r) >= 30:
            out[lbl] = sharpe_ratio(r, periods_per_year)
    return out


# ---------------------------------------------------------------------
# Monthly returns
# ---------------------------------------------------------------------
def monthly_returns(equity: pd.Series) -> pd.Series:
    if equity is None or len(equity) < 2:
        return pd.Series(dtype=float)
    m = equity.resample("ME").last()
    return m.pct_change().dropna()
