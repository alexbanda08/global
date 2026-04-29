"""
polymarket_stats.py — equity-curve risk stats for backtest pnls.

Drop-in helper. Pure numpy. No external deps beyond what signal_grid_v2 already uses.

Adapted from AlphaPurify FactorAnalyzer.calc_stats_for_period (Sharpe/Sortino/Calmar/MaxDD block,
L621-650). Polymarket trades are one-shot per market; we treat each settled trade as one
"period" and compute equity-curve metrics on the cumulative pnl series.

Usage:
    from polymarket_stats import equity_curve_stats
    stats = equity_curve_stats(pnls, trade_timestamps=ws_array)
    # → dict with sharpe, sortino, calmar, max_dd, max_dd_pct, longest_dd_run, ...
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _safe(x: float) -> float:
    return float(x) if np.isfinite(x) else float("nan")


def equity_curve_stats(
    pnls: np.ndarray,
    trade_timestamps: np.ndarray | None = None,
    annual_factor: float | None = None,
    risk_free_per_trade: float = 0.0,
) -> dict:
    """
    Compute equity-curve risk stats from per-trade pnls.

    Parameters
    ----------
    pnls : np.ndarray
        Per-trade PnL in dollars (one entry per settled trade).
    trade_timestamps : np.ndarray | None
        Optional unix-seconds timestamp per trade. If provided, pnls are sorted
        chronologically before computing equity curve. If None, assumes input
        order is already chronological.
    annual_factor : float | None
        Number of trades per year for annualization. If None, attempts to infer
        from `trade_timestamps` (median trades/year). If still None, no annualization
        is applied (stats are per-trade).
    risk_free_per_trade : float
        Risk-free PnL per trade (default 0). Subtracted from mean before Sharpe.

    Returns
    -------
    dict with:
        n, total_pnl, mean_pnl, std_pnl,
        sharpe, sortino, calmar,
        max_dd, longest_dd_run,
        win_rate, equity_final, ann_factor_used

    Note: max_dd is in dollars (peak-to-trough on cumulative PnL). A "pct" version
    is intentionally NOT reported because per-$1-stake Polymarket trades have no
    well-defined initial-capital base; report max_dd in absolute terms and let the
    caller scale to whatever stake size is being modeled.
    """
    pnls = np.asarray(pnls, dtype=float)
    n = int(pnls.size)
    if n == 0:
        return {
            "n": 0, "total_pnl": 0.0, "mean_pnl": float("nan"), "std_pnl": float("nan"),
            "sharpe": float("nan"), "sortino": float("nan"), "calmar": float("nan"),
            "max_dd": float("nan"), "longest_dd_run": 0,
            "win_rate": float("nan"), "equity_final": 0.0, "ann_factor_used": float("nan"),
        }

    if trade_timestamps is not None:
        ts = np.asarray(trade_timestamps, dtype=float)
        order = np.argsort(ts)
        pnls = pnls[order]
        ts = ts[order]
    else:
        ts = None

    # Infer annualization factor if not given
    if annual_factor is None and ts is not None and n >= 2:
        span_s = ts[-1] - ts[0]
        if span_s > 0:
            annual_factor = n * (365.25 * 86400.0) / span_s

    mean_pnl = float(pnls.mean())
    std_pnl = float(pnls.std(ddof=0))
    excess = mean_pnl - risk_free_per_trade

    if annual_factor is not None and annual_factor > 0:
        ann_mean = excess * annual_factor
        ann_vol = std_pnl * np.sqrt(annual_factor)
    else:
        ann_mean = excess
        ann_vol = std_pnl
        annual_factor = float("nan")

    sharpe = ann_mean / ann_vol if ann_vol > 0 else float("nan")

    downside = pnls[pnls < 0]
    if downside.size > 0:
        downside_std = float(downside.std(ddof=1)) if downside.size > 1 else float(np.abs(downside).mean())
        if annual_factor is not None and not np.isnan(annual_factor):
            ann_downside_vol = downside_std * np.sqrt(annual_factor)
        else:
            ann_downside_vol = downside_std
        sortino = ann_mean / ann_downside_vol if ann_downside_vol > 0 else float("nan")
    else:
        sortino = float("nan")

    equity = np.cumsum(pnls)
    equity_with_zero = np.concatenate([[0.0], equity])
    running_max = np.maximum.accumulate(equity_with_zero)
    drawdown = equity_with_zero - running_max
    max_dd = float(drawdown.min())  # negative or zero, in dollars

    # Longest drawdown run (consecutive trades below previous peak)
    in_dd = drawdown < 0
    longest_dd_run = 0
    cur = 0
    for v in in_dd:
        if v:
            cur += 1
            if cur > longest_dd_run:
                longest_dd_run = cur
        else:
            cur = 0

    calmar = ann_mean / abs(max_dd) if max_dd < 0 else float("nan")

    return {
        "n": n,
        "total_pnl": _safe(equity[-1]),
        "mean_pnl": _safe(mean_pnl),
        "std_pnl": _safe(std_pnl),
        "sharpe": _safe(sharpe),
        "sortino": _safe(sortino),
        "calmar": _safe(calmar),
        "max_dd": _safe(max_dd),
        "longest_dd_run": int(longest_dd_run),
        "win_rate": _safe((pnls > 0).mean()),
        "equity_final": _safe(equity[-1]),
        "ann_factor_used": _safe(annual_factor),
    }


def equity_stats_from_dataframe(
    df: pd.DataFrame,
    pnl_col: str = "pnl",
    ts_col: str | None = "window_start_unix",
    annual_factor: float | None = None,
) -> dict:
    """Convenience wrapper for a per-trade pandas DataFrame."""
    pnls = df[pnl_col].to_numpy()
    ts = df[ts_col].to_numpy() if ts_col is not None and ts_col in df.columns else None
    return equity_curve_stats(pnls, trade_timestamps=ts, annual_factor=annual_factor)
