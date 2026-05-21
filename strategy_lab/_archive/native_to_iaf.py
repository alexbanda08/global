"""
native_to_iaf — adapter that converts our native backtest results
(equity Series + trades DataFrame) into IAF Backtest objects so we can
render the IAF HTML dashboard from OUR numbers.

Why: IAF's `run_vector_backtests` uses long-only + fixed %-SL/TP which
doesn't match our L/S + ATR-trail simulator.  But IAF's HTML dashboard
is really good — equity overlay, monthly heatmap, leaderboard.  So we
keep our simulator for the math and reuse IAF only for the UI.

Usage:
    from strategy_lab.native_to_iaf import render_native_dashboard
    render_native_dashboard(
        entries=[
            ("V15 Balanced",  eq_v15,  trades_v15),
            ("V24 MF 1x",     eq_v24,  trades_v24),
            ("V27 L/S 0.5x",  eq_v27,  trades_v27),
            ("USER 5-sleeve", eq_user, trades_user),
        ],
        output_html="reports/NATIVE_DASHBOARD.html",
        trading_symbol="USDT",
        initial_balance=10_000,
    )

The dashboard is 1 self-contained HTML file — drop it anywhere and it opens
in a browser.  No server, no flask.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
import math
import shutil
import uuid

import numpy as np
import pandas as pd

from investing_algorithm_framework import (
    Backtest, BacktestReport, BacktestRun, Trade,
)
from investing_algorithm_framework.domain.backtesting.backtest_metrics import BacktestMetrics
from investing_algorithm_framework.domain.backtesting.backtest_summary_metrics import BacktestSummaryMetrics
from investing_algorithm_framework.domain.backtesting.backtest_date_range import BacktestDateRange


# ---------------------------------------------------------------------
def _to_py_dt(ts) -> datetime:
    """Any -> timezone-aware UTC datetime."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


def _monthly_returns(eq: pd.Series) -> list[tuple[float, datetime]]:
    m = eq.resample("1ME").last().pct_change(fill_method=None).dropna()
    return [(float(v), _to_py_dt(t)) for t, v in m.items()]


def _yearly_returns(eq: pd.Series) -> list[tuple[float, datetime]]:
    y = eq.resample("1YE").last().pct_change(fill_method=None).dropna()
    return [(float(v), _to_py_dt(t)) for t, v in y.items()]


def _drawdown_series(eq: pd.Series) -> list[tuple[float, datetime]]:
    dd = eq / eq.cummax() - 1
    return [(float(v), _to_py_dt(t)) for t, v in dd.items()]


def _rolling_sharpe(eq: pd.Series, window_bars: int = 252, bpy: float = 365.25*24/4):
    rets = eq.pct_change(fill_method=None).fillna(0)
    rs = rets.rolling(window_bars).apply(
        lambda r: (r.mean()*bpy) / (r.std()*np.sqrt(bpy) + 1e-12))
    rs = rs.dropna()
    return [(float(v), _to_py_dt(t)) for t, v in rs.items()]


def _build_trade(row: pd.Series, target_symbol: str, trading_symbol: str) -> Trade:
    """Minimal IAF Trade from a native trade row.

    Expected columns: entry_time, exit_time, entry_price, exit_price,
                      shares (or size), return (fractional).
    net_gain is computed in the trading currency.
    """
    entry = _to_py_dt(row.get("entry_time") or row.get("opened_at"))
    ex_ts = row.get("exit_time") or row.get("closed_at")
    closed = _to_py_dt(ex_ts) if pd.notna(ex_ts) else entry
    entry_px = float(row.get("entry_price", 0.0))
    exit_px  = float(row.get("exit_price",  entry_px))
    amount   = float(row.get("shares", row.get("size", 1.0)))
    net_gain = float(row.get("net_gain", (exit_px - entry_px) * amount))
    cost     = float(entry_px * amount)
    return Trade(
        id=str(uuid.uuid4()),
        orders=[],
        target_symbol=target_symbol,
        trading_symbol=trading_symbol,
        status="CLOSED",
        amount=amount,
        remaining=0.0,
        available_amount=0.0,
        filled_amount=amount,
        open_price=entry_px,
        last_reported_price=exit_px,
        opened_at=entry,
        closed_at=closed,
        updated_at=closed,
        net_gain=net_gain,
        cost=cost,
    )


# ---------------------------------------------------------------------
def native_to_backtest(
    equity: pd.Series,
    trades: pd.DataFrame | None,
    algorithm_id: str,
    trading_symbol: str = "USDT",
    initial_balance: float = 10_000.0,
    target_symbol: str | None = None,
    bars_per_year: float = 365.25 * 24 / 4,
) -> Backtest:
    """Convert our native (equity, trades) into an IAF Backtest object."""
    if not isinstance(equity.index, pd.DatetimeIndex):
        equity.index = pd.to_datetime(equity.index)
    if equity.index.tz is None:
        equity.index = equity.index.tz_localize("UTC")

    start = _to_py_dt(equity.index[0])
    end   = _to_py_dt(equity.index[-1])
    n_days = max(1, (end - start).days)

    # Metrics
    rets = equity.pct_change(fill_method=None).fillna(0)
    mean_r = rets.mean(); std_r = rets.std()
    sharpe = (mean_r * bars_per_year) / (std_r * np.sqrt(bars_per_year) + 1e-12)
    # Sortino (downside stdev)
    downside = rets[rets < 0]
    sortino = (mean_r * bars_per_year) / (downside.std() * np.sqrt(bars_per_year) + 1e-12) \
              if len(downside) else 0.0
    yrs = n_days / 365.25
    initial = float(equity.iloc[0])
    final   = float(equity.iloc[-1])
    growth_pct = (final / initial) - 1
    cagr = (final / initial) ** (1 / max(yrs, 1e-6)) - 1 if initial > 0 else 0
    dd_series = equity / equity.cummax() - 1
    max_dd = float(dd_series.min())
    max_dd_abs = float((equity - equity.cummax()).min())
    # DD duration: longest consecutive run below peak
    below = dd_series < 0
    longest = 0; run = 0
    for b in below.values:
        run = run + 1 if b else 0
        longest = max(longest, run)
    # Monthly / yearly
    monthly = _monthly_returns(equity)
    yearly  = _yearly_returns(equity)
    # Volatility
    ann_vol = float(std_r * np.sqrt(bars_per_year))
    # Trades
    tr_objs: list[Trade] = []
    if trades is not None and len(trades):
        coin = target_symbol or "BTC"
        for _, row in trades.iterrows():
            tr_objs.append(_build_trade(row, coin, trading_symbol))

    # Per-trade stats
    if tr_objs:
        pnls = np.array([t.net_gain for t in tr_objs])
        gross_p = float(pnls[pnls > 0].sum()); gross_l = float(abs(pnls[pnls < 0].sum()))
        pf = gross_p / gross_l if gross_l > 0 else 0.0
        wr = float((pnls > 0).mean()); n_pos = int((pnls > 0).sum()); n_neg = int((pnls <= 0).sum())
        avg_gain = float(pnls[pnls > 0].mean()) if n_pos else 0
        avg_loss = float(pnls[pnls <= 0].mean()) if n_neg else 0
        durations = [(t.closed_at - t.opened_at).total_seconds() / 3600 for t in tr_objs]
        avg_dur = float(np.mean(durations)) if durations else 0
    else:
        pf = 0.0; wr = 0.0; n_pos = 0; n_neg = 0
        gross_p = gross_l = 0.0; avg_gain = avg_loss = 0.0; avg_dur = 0.0

    # VaR / CVaR on per-bar returns
    rr = rets.dropna().values
    if len(rr):
        var95  = float(np.quantile(rr, 0.05))
        cvar95 = float(rr[rr <= var95].mean()) if (rr <= var95).any() else var95
    else:
        var95 = cvar95 = 0.0

    # Calmar
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0

    trades_per_year = len(tr_objs) / max(yrs, 1e-6)

    metrics = BacktestMetrics(
        backtest_start_date=start, backtest_end_date=end,
        backtest_date_range_name=f"{start.date()}_to_{end.date()}",
        trading_symbol=trading_symbol,
        initial_unallocated=initial_balance,
        equity_curve=[(float(v), _to_py_dt(t)) for t, v in equity.items()],
        total_growth=final - initial, total_growth_percentage=float(growth_pct),
        total_net_gain=final - initial, total_net_gain_percentage=float(growth_pct),
        total_loss=abs(min(0.0, final - initial)), total_loss_percentage=abs(min(0.0, float(growth_pct))),
        final_value=final, cumulative_return=float(growth_pct),
        cumulative_return_series=[(float(v/initial - 1), _to_py_dt(t)) for t, v in equity.items()],
        cagr=float(cagr), sharpe_ratio=float(sharpe),
        rolling_sharpe_ratio=_rolling_sharpe(equity, 252, bars_per_year),
        sortino_ratio=float(sortino), calmar_ratio=float(calmar),
        profit_factor=float(pf),
        gross_profit=float(gross_p), gross_loss=float(gross_l),
        annual_volatility=ann_vol,
        monthly_returns=monthly, yearly_returns=yearly,
        drawdown_series=[(float(v), _to_py_dt(t)) for t, v in dd_series.items()],
        max_drawdown=abs(float(max_dd)), max_drawdown_absolute=abs(max_dd_abs),
        max_daily_drawdown=0.0, max_drawdown_duration=longest,
        trades_per_year=float(trades_per_year),
        trades_per_week=float(trades_per_year/52),
        trades_per_month=float(trades_per_year/12),
        trade_per_day=float(trades_per_year/365.25),
        exposure_ratio=1.0, cumulative_exposure=1.0,
        number_of_positive_trades=n_pos,
        percentage_positive_trades=float(n_pos / max(1, len(tr_objs))),
        number_of_negative_trades=n_neg,
        percentage_negative_trades=float(n_neg / max(1, len(tr_objs))),
        average_trade_duration=float(avg_dur),
        average_win_duration=float(avg_dur), average_loss_duration=float(avg_dur),
        average_trade_size=float(initial_balance),
        average_trade_loss=float(avg_loss), average_trade_loss_percentage=0.0,
        average_trade_gain=float(avg_gain), average_trade_gain_percentage=0.0,
        average_trade_return=float((gross_p - gross_l)/max(1, len(tr_objs))),
        average_trade_return_percentage=0.0,
        number_of_trades=len(tr_objs), number_of_trades_closed=len(tr_objs),
        number_of_trades_opened=len(tr_objs), number_of_trades_open_at_end=0,
        win_rate=float(wr), current_win_rate=float(wr),
        win_loss_ratio=float(pf), current_win_loss_ratio=float(pf),
        percentage_winning_months=float((pd.Series([m[0] for m in monthly]) > 0).mean()) if monthly else 0,
        percentage_winning_years=float((pd.Series([y[0] for y in yearly]) > 0).mean()) if yearly else 0,
        average_monthly_return=float(np.mean([m[0] for m in monthly])) if monthly else 0,
        average_monthly_return_losing_months=0, average_monthly_return_winning_months=0,
        total_number_of_days=n_days,
        var_95=var95, cvar_95=cvar95,
        max_consecutive_wins=0, max_consecutive_losses=0,
    )

    run = BacktestRun(
        backtest_start_date=start, backtest_end_date=end,
        trading_symbol=trading_symbol, initial_unallocated=initial_balance,
        number_of_runs=1, portfolio_snapshots=[], trades=tr_objs,
        orders=[], positions=[], created_at=datetime.now(timezone.utc),
        symbols=[target_symbol or "BTC"], number_of_days=n_days,
        number_of_trades=len(tr_objs), number_of_trades_closed=len(tr_objs),
        number_of_trades_open=0, number_of_orders=0, number_of_positions=0,
        backtest_metrics=metrics,
        backtest_date_range_name=f"{start.date()}_to_{end.date()}",
    )

    summary = BacktestSummaryMetrics(
        total_net_gain=final - initial, total_net_gain_percentage=growth_pct,
        total_growth=final - initial, total_growth_percentage=growth_pct,
        total_loss=0, total_loss_percentage=0,
        cagr=float(cagr), sharpe_ratio=float(sharpe),
        sortino_ratio=float(sortino), calmar_ratio=float(calmar),
        profit_factor=float(pf), annual_volatility=ann_vol,
        max_drawdown=abs(float(max_dd)),
        max_drawdown_duration=longest,
        trades_per_year=float(trades_per_year),
        trades_per_month=float(trades_per_year/12),
        trades_per_week=float(trades_per_year/52),
        win_rate=float(wr), current_win_rate=float(wr),
        win_loss_ratio=float(pf), current_win_loss_ratio=float(pf),
        number_of_trades=len(tr_objs), number_of_trades_closed=len(tr_objs),
        cumulative_exposure=1.0, exposure_ratio=1.0,
        number_of_windows=1, number_of_profitable_windows=1 if growth_pct > 0 else 0,
        number_of_windows_with_trades=1,
        var_95=var95, cvar_95=cvar95,
        average_trade_duration=float(avg_dur),
        average_win_duration=float(avg_dur), average_loss_duration=float(avg_dur),
        max_consecutive_wins=0, max_consecutive_losses=0,
    )

    bt = Backtest(
        algorithm_id=algorithm_id,
        backtest_runs=[run],
        backtest_summary=summary,
        metadata={"source": "native_simulator"},
        risk_free_rate=0.0,
    )
    return bt


# ---------------------------------------------------------------------
def render_native_dashboard(entries, output_html: str,
                            trading_symbol: str = "USDT",
                            initial_balance: float = 10_000.0,
                            storage_dir: str | Path | None = None,
                            target_symbol_map: dict[str,str] | None = None):
    """
    entries: list of (label, equity_series, trades_df_or_None)
    output_html: where to write the final dashboard HTML
    storage_dir: intermediate dir for IAF backtest dumps (temp if None)
    target_symbol_map: optional label -> target_symbol mapping
    """
    if storage_dir is None:
        storage_dir = Path("strategy_lab/results/native_iaf/backtests")
    storage_dir = Path(storage_dir); storage_dir.mkdir(parents=True, exist_ok=True)

    tmap = target_symbol_map or {}

    # Wipe existing backtests to avoid stale runs polluting the dashboard
    if storage_dir.exists():
        shutil.rmtree(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)

    bts = []
    for label, eq, trs in entries:
        target_sym = tmap.get(label, "BTC")
        bt = native_to_backtest(
            equity=eq, trades=trs, algorithm_id=label,
            trading_symbol=trading_symbol,
            initial_balance=initial_balance,
            target_symbol=target_sym,
        )
        # Each backtest gets its own subdirectory derived from its algorithm_id.
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        bt.save(directory_path=str(storage_dir / safe))
        bts.append(bt)

    # Patch IAF's template reader for cp1252 Windows bug
    import investing_algorithm_framework.app.reporting.backtest_report as r
    def _read_template_utf8(name):
        import os
        tpl = os.path.join(os.path.dirname(r.__file__), "templates", name)
        with open(tpl, "r", encoding="utf-8") as f:
            return f.read()
    r._read_template = _read_template_utf8

    report = BacktestReport.open(directory_path=str(storage_dir))
    out = Path(output_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    report.save(str(out))
    return out, report


# ---------------------------------------------------------------------
if __name__ == "__main__":
    # Demo: load our saved V15 / V24 / V27 / USER equity curves and generate
    # the IAF HTML dashboard from them.
    import sys
    print("Building native IAF dashboard from saved equity + trades CSVs...")
    V35 = Path("strategy_lab/results/v35_cross")
    eq_df = pd.read_csv(V35/"sleeve_equities_2023plus_normed.csv",
                        index_col=0, parse_dates=[0])
    eq_df.index = eq_df.index.tz_convert("UTC") if eq_df.index.tz else eq_df.index.tz_localize("UTC")

    entries = []
    for col, label in [("USER_5SLEEVE_EQW", "USER 5-Sleeve (Native)"),
                       ("MY_V15_BALANCED",  "V15 Balanced XSM (Native)"),
                       ("MY_V24_MF_1x",     "V24 Multi-filter XSM (Native)"),
                       ("MY_V27_LS_0.5x",   "V27 L/S 0.5x (Native)")]:
        if col not in eq_df.columns: continue
        eq = eq_df[col].dropna()
        # Trades: we don't have per-strategy trade logs for XSM variants,
        # but we can still render the equity-based dashboard without trades.
        entries.append((label, eq, None))

    out, _ = render_native_dashboard(
        entries=entries,
        output_html="strategy_lab/reports/NATIVE_DASHBOARD.html",
        initial_balance=10_000.0,
    )

    pub = Path("C:/Users/alexandre bandarra/Desktop/newstrategies/NATIVE_DASHBOARD.html")
    pub.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, pub)
    print(f"Wrote  {out}")
    print(f"Copied {pub}")
