"""
Strategy Lab — Backtesting Engine
==================================

Thin wrapper around vectorbt 0.28.x that enforces best practices to avoid
look-ahead bias and match TradingView's Strategy Tester semantics.

Design rules (MUST match in Pine conversion):
  * Signals computed on bar i execute at the OPEN of bar i+1
    (vbt default `price=close` + `accumulate=False` would exit on same-bar;
     we explicitly shift signals by +1 and fill execution price with `open`).
  * Fees:     0.001 (0.1% Binance spot, per side).
  * Slippage: 0.0005 (5 bps).
  * No stop-loss touches same-bar as entry.
  * Single position per symbol (size_type='value', size=np.inf to use cash).

This module is deliberately small and readable — the complexity lives in
strategies.py.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd
import vectorbt as vbt

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------
# Data root
# ---------------------------------------------------------------------
PARQUET_ROOT = Path(__file__).resolve().parent.parent / "data" / "binance" / "parquet"


# ---------------------------------------------------------------------
# Execution constants (Binance spot)
# ---------------------------------------------------------------------
FEE   = 0.001      # 0.1% per side
SLIP  = 0.0005     # 5 bps

# Risk-adjusted portfolio allocation — riskier assets get less starting capital.
# Based on realized-vol ranking over 2021-2024 on the 1d series
# (SOL > ETH > BTC). Keeps BTC as the anchor.
PORTFOLIO_ALLOC = {
    "BTCUSDT": 0.50,
    "ETHUSDT": 0.30,
    "SOLUSDT": 0.20,
}
TOTAL_CAPITAL = 10_000.0


# ---------------------------------------------------------------------
# Phase 0.5a scaffolding — fee schedules & execution config.
#
# New code paths are opt-in via `run_backtest(..., execution=...)`.
# When `execution is None` or `execution.mode == "v1"`, the engine
# routes through the exact same vectorbt call that existed before this
# uplift, so legacy runners are bit-identical. See docs/research/
# 0_5_ENGINE_UPLIFT_SPEC.md for the full design.
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class FeeSchedule:
    """Maker/taker fee schedule for a specific exchange/tier."""
    exchange_name: str
    maker_bps: float
    taker_bps: float
    effective_date: date = field(default_factory=lambda: date(2024, 1, 1))
    notes: str = ""


# Public registry. `binance_spot_legacy` deliberately mirrors the flat
# FEE = 0.001 constant so `mode="v1"` can source its fee from here if we
# later wire v1 through the generic path. Callers can register custom
# schedules via `register_fee_schedule`.
FEE_REGISTRY: dict[str, FeeSchedule] = {
    "binance_spot_legacy": FeeSchedule("binance_spot_legacy", 10.0, 10.0, date(2020, 1, 1),
                                       "flat 10bps per side (mirrors engine.FEE)"),
    "binance_spot":        FeeSchedule("binance_spot",        10.0, 10.0, date(2024, 1, 1)),
    "binance_vip0":        FeeSchedule("binance_vip0",        10.0, 10.0, date(2024, 1, 1)),
    "bybit_spot":          FeeSchedule("bybit_spot",          10.0, 10.0, date(2024, 1, 1)),
    "bybit_perp":          FeeSchedule("bybit_perp",           2.0,  5.5, date(2024, 1, 1)),
    "hyperliquid":         FeeSchedule("hyperliquid",          1.5,  3.5, date(2024, 1, 1)),
}


def register_fee_schedule(fs: FeeSchedule) -> None:
    """Add (or override) a fee schedule in the global registry."""
    FEE_REGISTRY[fs.exchange_name] = fs


def resolve_fee_schedule(ref: "str | FeeSchedule") -> FeeSchedule:
    if isinstance(ref, FeeSchedule):
        return ref
    try:
        return FEE_REGISTRY[ref]
    except KeyError as e:
        raise KeyError(
            f"Unknown fee schedule {ref!r}. Registered: {sorted(FEE_REGISTRY)}"
        ) from e


@dataclass(frozen=True)
class ExecutionConfig:
    """
    Controls order-type + fee + fill semantics.

    Default (`mode="v1"`) reproduces the pre-uplift engine exactly:
    market fill at next-bar open, flat 10 bps fees per side, 5 bps slip.
    Non-default modes are wired in Phase 0.5b / 0.5c.
    """
    mode: Literal["v1", "market", "limit", "hybrid"] = "v1"
    fee_schedule: "str | FeeSchedule" = "binance_spot_legacy"
    slippage_bps: float = 5.0                    # taker slippage only
    limit_mode: "Literal['at_close', 'offset_pct', 'ladder', 'stop_limit'] | None" = None
    limit_offset_pct: float = 0.0
    limit_ladder_pcts: tuple = ()
    limit_ladder_weights: tuple = ()
    limit_valid_bars: int = 3                    # N — cancel after N bars unfilled
    stop_trigger_pct: float = 0.0
    stop_limit_inside_pct: float = 0.0
    max_fill_pct_of_bar_volume: float = 0.10     # P — partial-fill cap
    hybrid_fallback_after_bars: int = 3
    queue_position_penalty_bps: float = 1.0
    report_unfilled: bool = True


def _empty_fills_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "ts", "side", "size", "price", "fee", "is_maker",
        "slippage_bps", "order_id", "parent_signal_ts",
    ])


def _empty_unfilled_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "ts_posted", "side", "limit_price", "expired_at", "reason",
    ])


def _empty_execution_metrics() -> dict:
    """Default-shaped execution_metrics for v1 mode (no limit accounting)."""
    return {
        "maker_fill_pct":         0.0,  # v1: all fills are market/taker-equivalent
        "taker_fill_pct":         1.0,
        "unfilled_order_count":   0,
        "unfilled_order_pct":     0.0,
        "total_fee_paid":         None,
        "fee_drag_pct_of_pnl":    None,
        "avg_entry_slippage_bps": None,
        "avg_exit_slippage_bps":  None,
        "avg_slippage_per_trade": None,
        "partial_fill_ratio":     0.0,
        "avg_fills_per_order":    1.0,
        "mode":                   "v1",
    }


# ---------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------
def load(symbol: str, tf: str,
         start: str = "2018-01-01", end: str | None = None) -> pd.DataFrame:
    """
    Load [start, end) bars for one symbol/timeframe.
    Returns a DataFrame indexed by open_time (tz-aware UTC) with OHLCV.

    Derived timeframes (no on-disk folder required):
      "2h"  → loaded from 1h data and resampled 2:1
      "30m" → loaded from 15m data and resampled 2:1
    label="right", closed="left": the bar label is the right edge, and the
    interval is closed on the left, so the 2h bar labelled 08:00 covers
    [06:00, 08:00) — no look-ahead.
    """
    # --- derived-timeframe resample path -----------------------------------
    _DERIVED = {
        "2h":  ("1h",  "2h"),
        "30m": ("15m", "30min"),
    }
    if tf in _DERIVED:
        src_tf, resample_rule = _DERIVED[tf]
        src_folder = PARQUET_ROOT / symbol / src_tf
        if not src_folder.exists():
            raise FileNotFoundError(
                f"Derived tf {tf!r} needs {src_tf!r} source, "
                f"but folder not found: {src_folder}"
            )
        df_src = load(symbol, src_tf, start=start, end=end)
        df = df_src.resample(
            resample_rule, label="right", closed="left"
        ).agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
        }).dropna(subset=["open"])
        return df.astype("float64")
    # -----------------------------------------------------------------------

    folder = PARQUET_ROOT / symbol / tf
    if not folder.exists():
        raise FileNotFoundError(folder)

    frames = [pd.read_parquet(f) for f in sorted(folder.glob("year=*/part.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    df = (df.drop_duplicates("open_time")
            .sort_values("open_time")
            .set_index("open_time"))

    start_ts = pd.Timestamp(start, tz="UTC")
    df = df[df.index >= start_ts]
    if end:
        end_ts = pd.Timestamp(end, tz="UTC")
        df = df[df.index < end_ts]

    return df[["open", "high", "low", "close", "volume"]].astype("float64")


# ---------------------------------------------------------------------
# Backtest runner — strict next-bar-open execution
# ---------------------------------------------------------------------
@dataclass
class BacktestResult:
    pf: "vbt.Portfolio"
    metrics: dict
    # New in Phase 0.5a — always present so downstream tooling can count
    # on a consistent shape. In v1 mode these are empty/neutral.
    fills: pd.DataFrame = field(default_factory=_empty_fills_df)
    unfilled_orders: pd.DataFrame = field(default_factory=_empty_unfilled_df)
    execution_metrics: dict = field(default_factory=_empty_execution_metrics)


def run_backtest(df: pd.DataFrame,
                 entries: pd.Series, exits: pd.Series,
                 short_entries: pd.Series | None = None,
                 short_exits: pd.Series | None = None,
                 sl_stop: pd.Series | float | None = None,
                 tsl_stop: pd.Series | float | None = None,
                 tp_stop: pd.Series | float | None = None,
                 init_cash: float = 10_000.0,
                 label: str = "",
                 *,
                 execution: ExecutionConfig | None = None) -> BacktestResult:
    """
    Run a single-asset backtest with strict rules:
      * Signal on bar i → fill at open of bar i+1 (shift by +1)
      * Fill price: next bar OPEN (`price=open`)
      * Fees + slippage baked in.

    `execution` (keyword-only) — Phase-0.5 opt-in. `None` and
    `ExecutionConfig(mode="v1")` both route through the legacy vectorbt
    path with flat fees and market fills. Non-v1 modes are implemented
    in Phase 0.5b/c; v1 is the only active path in 0.5a.
    """
    if execution is not None:
        if execution.mode == "market":
            return _run_market_mode(
                df, entries, exits, short_entries, short_exits,
                sl_stop, tsl_stop, tp_stop, init_cash, label, execution,
            )
        if execution.mode == "limit":
            return _run_limit_mode(
                df, entries, exits, short_entries, short_exits,
                sl_stop, tsl_stop, tp_stop, init_cash, label, execution,
            )
        if execution.mode != "v1":
            raise NotImplementedError(
                f"ExecutionConfig.mode={execution.mode!r} is not implemented until "
                "Phase 0.5c. See docs/research/0_5_ENGINE_UPLIFT_SPEC.md § 7."
            )
    # Shift signals by 1 — critical for no look-ahead.
    entries = entries.shift(1).fillna(False).astype(bool)
    exits   = exits.shift(1).fillna(False).astype(bool)

    # Infer bar frequency so vbt can compute risk-adjusted metrics.
    dt = df.index.to_series().diff().median()
    freq = pd.tseries.frequencies.to_offset(dt) if dt is not None else None

    kwargs = dict(
        close=df["close"],
        entries=entries,
        exits=exits,
        price=df["open"],          # execution at bar open
        init_cash=init_cash,
        fees=FEE,
        slippage=SLIP,
        freq=freq,
        size=np.inf,
        size_type="value",
        direction="longonly",
    )

    if short_entries is not None and short_exits is not None:
        se = short_entries.shift(1).fillna(False).astype(bool)
        sx = short_exits.shift(1).fillna(False).astype(bool)
        kwargs.update(short_entries=se, short_exits=sx, direction="both")

    # vbt 0.28 uses sl_stop + sl_trail (boolean) for trailing stops.
    # If both fixed and trailing are supplied, prefer trailing (tighter).
    if tsl_stop is not None:
        kwargs["sl_stop"] = tsl_stop
        kwargs["sl_trail"] = True
    elif sl_stop is not None:
        kwargs["sl_stop"] = sl_stop
        kwargs["sl_trail"] = False
    if tp_stop is not None:
        kwargs["tp_stop"] = tp_stop

    pf = vbt.Portfolio.from_signals(**kwargs)

    return BacktestResult(pf=pf, metrics=extract_metrics(pf, label=label))


# ---------------------------------------------------------------------
# Metrics extractor
# ---------------------------------------------------------------------
def extract_metrics(pf: "vbt.Portfolio", label: str = "") -> dict:
    """
    Return a flat dict of the metrics we track.
    Safe against empty trade sets.
    """
    trades = pf.trades
    n_trades = int(trades.count())

    try:
        total_return = float(pf.total_return())
    except Exception:
        total_return = 0.0

    try:
        sharpe = float(pf.sharpe_ratio())
    except Exception:
        sharpe = 0.0
    try:
        sortino = float(pf.sortino_ratio())
    except Exception:
        sortino = 0.0
    try:
        max_dd = float(pf.max_drawdown())
    except Exception:
        max_dd = 0.0
    try:
        calmar = float(pf.calmar_ratio())
    except Exception:
        calmar = 0.0

    if n_trades > 0:
        try:
            win_rate = float(trades.win_rate())
        except Exception:
            win_rate = 0.0
        try:
            pf_ratio = float(trades.profit_factor())
        except Exception:
            pf_ratio = 0.0
        try:
            avg_win = float(trades.winning.pnl.mean() or 0.0)
        except Exception:
            avg_win = 0.0
        try:
            avg_loss = float(trades.losing.pnl.mean() or 0.0)
        except Exception:
            avg_loss = 0.0
        try:
            exposure = float(pf.trades.records_readable["Duration"].astype("timedelta64[m]").astype(int).sum())
        except Exception:
            exposure = 0
    else:
        win_rate = pf_ratio = avg_win = avg_loss = 0.0
        exposure = 0

    # CAGR from equity curve
    eq = pf.value()
    if len(eq) > 2:
        years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400.0)
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1.0 / max(years, 1e-6)) - 1.0
    else:
        cagr = 0.0

    # Buy & Hold benchmark
    try:
        bh = float(pf.total_benchmark_return())
    except Exception:
        bh = 0.0

    return {
        "label":       label,
        "total_return":total_return,
        "cagr":        float(cagr),
        "sharpe":      sharpe,
        "sortino":     sortino,
        "calmar":      calmar,
        "max_dd":      max_dd,
        "n_trades":    n_trades,
        "win_rate":    win_rate,
        "profit_factor": pf_ratio,
        "avg_win":     avg_win,
        "avg_loss":    avg_loss,
        "bh_return":   bh,
        "final_equity":float(eq.iloc[-1]) if len(eq) else 0.0,
    }


# ---------------------------------------------------------------------
# Phase 0.5b — market & limit mode implementations.
# ---------------------------------------------------------------------
def _build_execution_metrics(
    fills_df: pd.DataFrame,
    unfilled_df: pd.DataFrame,
    gross_pnl: float | None,
    mode: str,
) -> dict:
    """Populate the execution_metrics dict from a fills/unfilled pair."""
    n_fills = len(fills_df)
    if n_fills > 0:
        maker_pct = float(fills_df["is_maker"].sum()) / n_fills
        total_fee = float(fills_df["fee"].sum())
    else:
        maker_pct = 0.0 if mode != "v1" else 0.0
        total_fee = 0.0

    taker_pct = 1.0 - maker_pct
    n_unfilled = int(len(unfilled_df))

    # Parent orders = distinct order_ids in fills + unfilled rows.
    if n_fills > 0 and "order_id" in fills_df.columns:
        n_filled_parents = fills_df["order_id"].nunique()
    else:
        n_filled_parents = 0
    n_parents = n_filled_parents + n_unfilled

    unfilled_pct = (n_unfilled / n_parents) if n_parents > 0 else 0.0
    avg_fills_per_order = (n_fills / n_parents) if n_parents > 0 else (
        1.0 if mode == "v1" else 0.0
    )

    if gross_pnl is not None and gross_pnl != 0:
        fee_drag = float(total_fee / abs(gross_pnl))
    else:
        fee_drag = None

    # Slippage tracking: populated in fills_df["slippage_bps"].
    if n_fills > 0:
        entry_mask = fills_df["side"] == "buy"
        exit_mask  = fills_df["side"] == "sell"
        avg_entry_slip = float(fills_df.loc[entry_mask, "slippage_bps"].mean()) if entry_mask.any() else 0.0
        avg_exit_slip  = float(fills_df.loc[exit_mask, "slippage_bps"].mean())  if exit_mask.any()  else 0.0
        avg_slip_trade = float(fills_df["slippage_bps"].mean())
    else:
        avg_entry_slip = avg_exit_slip = avg_slip_trade = 0.0 if mode == "v1" else None

    # partial_fill_ratio: fraction of fills that are part of a multi-fill parent.
    if n_fills > 0 and "order_id" in fills_df.columns:
        counts = fills_df.groupby("order_id").size()
        partial_fills = int(counts[counts > 1].sum())
        partial_ratio = partial_fills / n_fills
    else:
        partial_ratio = 0.0

    return {
        "maker_fill_pct":         maker_pct,
        "taker_fill_pct":         taker_pct,
        "unfilled_order_count":   n_unfilled,
        "unfilled_order_pct":     float(unfilled_pct),
        "total_fee_paid":         float(total_fee),
        "fee_drag_pct_of_pnl":    fee_drag,
        "avg_entry_slippage_bps": avg_entry_slip,
        "avg_exit_slippage_bps":  avg_exit_slip,
        "avg_slippage_per_trade": avg_slip_trade,
        "partial_fill_ratio":     float(partial_ratio),
        "avg_fills_per_order":    float(avg_fills_per_order),
        "mode":                   mode,
    }


def _fills_from_vbt_trades(
    pf: "vbt.Portfolio",
    df: pd.DataFrame,
    taker_bps: float,
    slippage_bps: float,
) -> pd.DataFrame:
    """
    Translate a vbt Portfolio's trades into the canonical fills DataFrame.
    Every round-trip trade produces 2 rows: one buy (entry) + one sell (exit).
    All market-mode fills are taker.
    """
    try:
        trades = pf.trades.records_readable
    except Exception:
        return _empty_fills_df()
    if trades is None or len(trades) == 0:
        return _empty_fills_df()

    out_rows = []
    for row_idx, tr in trades.iterrows():
        entry_ts = tr.get("Entry Timestamp", tr.get("Entry Date"))
        exit_ts  = tr.get("Exit Timestamp",  tr.get("Exit Date"))
        size     = float(tr.get("Size", 0.0))
        entry_px = float(tr.get("Avg Entry Price", tr.get("Entry Price", 0.0)))
        exit_px  = float(tr.get("Avg Exit Price",  tr.get("Exit Price",  0.0)))
        entry_fee = float(tr.get("Entry Fees", size * entry_px * taker_bps / 1e4))
        exit_fee  = float(tr.get("Exit Fees",  size * exit_px  * taker_bps / 1e4))
        direction = str(tr.get("Direction", "Long")).lower()

        buy_side  = "buy"  if direction.startswith("long") else "sell"
        sell_side = "sell" if direction.startswith("long") else "buy"

        out_rows.append({
            "ts": entry_ts, "side": buy_side, "size": size, "price": entry_px,
            "fee": entry_fee, "is_maker": False, "slippage_bps": float(slippage_bps),
            "order_id": f"M{row_idx}-entry", "parent_signal_ts": entry_ts,
        })
        out_rows.append({
            "ts": exit_ts, "side": sell_side, "size": size, "price": exit_px,
            "fee": exit_fee, "is_maker": False, "slippage_bps": float(slippage_bps),
            "order_id": f"M{row_idx}-exit", "parent_signal_ts": entry_ts,
        })

    return pd.DataFrame(out_rows, columns=_empty_fills_df().columns)


def _run_market_mode(df, entries, exits, short_entries, short_exits,
                     sl_stop, tsl_stop, tp_stop, init_cash, label, execution):
    """vbt next-bar-open fill, but fees come from the FeeSchedule.taker_bps."""
    fs = resolve_fee_schedule(execution.fee_schedule)
    fee_rate = fs.taker_bps / 1e4
    slip = execution.slippage_bps / 1e4

    entries = entries.shift(1).fillna(False).astype(bool)
    exits   = exits.shift(1).fillna(False).astype(bool)

    dt = df.index.to_series().diff().median()
    freq = pd.tseries.frequencies.to_offset(dt) if dt is not None else None

    kwargs = dict(
        close=df["close"], entries=entries, exits=exits,
        price=df["open"], init_cash=init_cash, fees=fee_rate, slippage=slip,
        freq=freq, size=np.inf, size_type="value", direction="longonly",
    )
    if short_entries is not None and short_exits is not None:
        se = short_entries.shift(1).fillna(False).astype(bool)
        sx = short_exits.shift(1).fillna(False).astype(bool)
        kwargs.update(short_entries=se, short_exits=sx, direction="both")
    if tsl_stop is not None:
        kwargs["sl_stop"] = tsl_stop
        kwargs["sl_trail"] = True
    elif sl_stop is not None:
        kwargs["sl_stop"] = sl_stop
        kwargs["sl_trail"] = False
    if tp_stop is not None:
        kwargs["tp_stop"] = tp_stop

    pf = vbt.Portfolio.from_signals(**kwargs)
    metrics = extract_metrics(pf, label=label)

    fills_df = _fills_from_vbt_trades(pf, df, taker_bps=fs.taker_bps,
                                      slippage_bps=execution.slippage_bps)
    unfilled_df = _empty_unfilled_df()
    # gross_pnl for fee_drag. final_equity - init_cash + fees ≈ gross.
    net_pnl = float(metrics.get("final_equity", init_cash) - init_cash)
    total_fee = float(fills_df["fee"].sum()) if len(fills_df) else 0.0
    gross_pnl = net_pnl + total_fee
    exec_metrics = _build_execution_metrics(fills_df, unfilled_df,
                                            gross_pnl=gross_pnl, mode="market")
    return BacktestResult(pf=pf, metrics=metrics, fills=fills_df,
                          unfilled_orders=unfilled_df,
                          execution_metrics=exec_metrics)


def _metrics_from_equity(
    equity: pd.Series,
    trade_records: list,
    label: str,
    init_cash: float,
) -> dict:
    """Flat metrics dict computed directly from an equity series + closed trades."""
    eq = equity.dropna()
    if len(eq) < 2:
        return dict(
            label=label, total_return=0.0, cagr=0.0, sharpe=0.0, sortino=0.0,
            calmar=0.0, max_dd=0.0, n_trades=0, win_rate=0.0,
            profit_factor=0.0, avg_win=0.0, avg_loss=0.0, bh_return=0.0,
            final_equity=float(eq.iloc[-1]) if len(eq) else float(init_cash),
        )

    final_eq = float(eq.iloc[-1])
    total_ret = final_eq / init_cash - 1.0
    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (final_eq / init_cash) ** (1.0 / max(years, 1e-6)) - 1.0

    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bars_per_year = pd.Timedelta(days=365.25) / dt if (dt and dt.value > 0) else 1
    mu = float(rets.mean()) if len(rets) else 0.0
    sd = float(rets.std()) if len(rets) > 1 else 0.0
    sharpe = (mu / sd) * np.sqrt(bars_per_year) if sd > 0 else 0.0
    dn_rets = rets[rets < 0]
    dn = float(dn_rets.std()) if len(dn_rets) > 1 else 0.0
    sortino = (mu / dn) * np.sqrt(bars_per_year) if dn > 0 else 0.0

    peak = eq.cummax()
    dd = (eq / peak - 1.0)
    max_dd = float(dd.min())
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0

    n_trades = len(trade_records)
    if n_trades > 0:
        pnls = np.asarray([t["pnl"] for t in trade_records], dtype=float)
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = float(len(wins) / n_trades)
        gw = float(wins.sum()); gl = float(-losses.sum())
        profit_factor = (gw / gl) if gl > 0 else 0.0
        avg_win = float(wins.mean()) if len(wins) else 0.0
        avg_loss = float(losses.mean()) if len(losses) else 0.0
    else:
        win_rate = profit_factor = avg_win = avg_loss = 0.0

    return dict(
        label=label, total_return=float(total_ret), cagr=float(cagr),
        sharpe=float(sharpe), sortino=float(sortino), calmar=float(calmar),
        max_dd=float(max_dd), n_trades=n_trades,
        win_rate=win_rate, profit_factor=float(profit_factor),
        avg_win=avg_win, avg_loss=avg_loss, bh_return=0.0,
        final_equity=final_eq,
    )


def _run_limit_mode(df, entries, exits, short_entries, short_exits,
                    sl_stop, tsl_stop, tp_stop, init_cash, label, execution):
    """
    Resting-limit fill simulation with intrabar touch logic.

    Scope of 0.5c (long-only, stops supported, shorts deferred):
      * Entry posts a buy limit at `close[i] * (1 - limit_offset_pct)`.
      * Exit posts a sell limit at `close[i] * (1 + limit_offset_pct)`.
      * Limit valid for `limit_valid_bars` bars after the signal bar.
      * Fill cap per bar: `max_fill_pct_of_bar_volume * volume[bar]`.
      * Fill price = L * (1 ± queue_position_penalty_bps/1e4).
      * Resting-limit fills are MAKER; stop-hit fills are TAKER (fs.taker_bps).
      * sl_stop / tsl_stop / tp_stop checked each bar while in position, AFTER
        the limit fill attempt on that bar. If a stop triggers, any resting
        exit limit is cancelled (logged as unfilled with reason=stop_override)
        and the position market-closes at the stop level with taker fee + slip.
      * No look-ahead: a limit posted at bar i cannot fill on bar i. Stops
        evaluate against bar i's intrabar high/low (representing market
        touches during the bar).
    """
    if short_entries is not None or short_exits is not None:
        raise NotImplementedError(
            "short-selling in limit mode is deferred to a later 0.5 stage."
        )
    # At most one of sl_stop / tsl_stop may be set (matches vbt v1 semantics).
    if sl_stop is not None and tsl_stop is not None:
        raise ValueError("cannot set both sl_stop and tsl_stop — pick one.")

    fs = resolve_fee_schedule(execution.fee_schedule)
    maker_rate = fs.maker_bps / 1e4
    taker_rate = fs.taker_bps / 1e4
    penalty = execution.queue_position_penalty_bps / 1e4
    slip = execution.slippage_bps / 1e4

    high_a   = df["high"].to_numpy(dtype=np.float64)
    low_a    = df["low"].to_numpy(dtype=np.float64)
    close_a  = df["close"].to_numpy(dtype=np.float64)
    volume_a = df["volume"].to_numpy(dtype=np.float64)
    entry_a  = entries.fillna(False).astype(bool).to_numpy()
    exit_a   = exits.fillna(False).astype(bool).to_numpy()
    n = len(df)
    idx = df.index

    cash = float(init_cash)
    pos_qty = 0.0
    active = None          # dict keeping the resting order state
    active_trade = None    # open-position bookkeeping
    tsl_peak_price = None  # highest-high-since-entry (for trailing stop)
    fills: list = []
    unfilled: list = []
    trades: list = []
    equity = np.zeros(n, dtype=np.float64)

    QTY_EPS = 1e-9     # treat residuals below this as fully filled

    for i in range(n):
        # --- 1) expire check FIRST: any order that has crossed its validity
        #       window cannot fill on this bar. Spec § 5.1: fills allowed for
        #       bars posted_idx+1 ... posted_idx+N (expires_at_idx = posted+N+1).
        if active is not None and i >= active["expires_at_idx"]:
            reason = "partial_expired" if active["qty_remaining"] < active["initial_qty"] - QTY_EPS else "expired"
            unfilled.append({
                "ts_posted": idx[active["posted_idx"]],
                "side": active["side"],
                "limit_price": active["L"],
                "expired_at": idx[i],
                "reason": reason,
            })
            active = None

        # --- 2) fill attempt on bar i (must be strictly after the post bar)
        if active is not None and i > active["posted_idx"]:
            if active["side"] == "buy":
                if low_a[i] <= active["L"]:
                    fill_px = active["L"] * (1.0 + penalty)
                    cap_qty = volume_a[i] * execution.max_fill_pct_of_bar_volume
                    this_qty = min(active["qty_remaining"], cap_qty)
                    notional = this_qty * fill_px
                    fee = notional * maker_rate
                    cost = notional + fee
                    cash_exhausted = False
                    if cost > cash + 1e-9:
                        # Rescale fill to available cash; order is done after this.
                        this_qty = cash / (fill_px * (1.0 + maker_rate)) if fill_px > 0 else 0.0
                        notional = this_qty * fill_px
                        fee = notional * maker_rate
                        cost = notional + fee
                        cash_exhausted = True
                    if this_qty > QTY_EPS:
                        cash -= cost
                        pos_qty += this_qty
                        fills.append({
                            "ts": idx[i], "side": "buy", "size": this_qty,
                            "price": fill_px, "fee": fee, "is_maker": True,
                            "slippage_bps": float(execution.queue_position_penalty_bps),
                            "order_id": f"L{active['posted_idx']}-buy",
                            "parent_signal_ts": idx[active["posted_idx"]],
                        })
                        if active_trade is None:
                            active_trade = {
                                "entry_idx": i, "entry_price": fill_px,
                                "qty": this_qty, "entry_fee": fee,
                            }
                        else:
                            total = active_trade["qty"] + this_qty
                            active_trade["entry_price"] = (
                                active_trade["entry_price"] * active_trade["qty"]
                                + fill_px * this_qty
                            ) / total
                            active_trade["qty"] = total
                            active_trade["entry_fee"] += fee
                        active["qty_remaining"] -= this_qty
                    if cash_exhausted or active["qty_remaining"] <= QTY_EPS:
                        active = None

            else:  # sell
                if high_a[i] >= active["L"]:
                    fill_px = active["L"] * (1.0 - penalty)
                    cap_qty = volume_a[i] * execution.max_fill_pct_of_bar_volume
                    this_qty = min(active["qty_remaining"], cap_qty, pos_qty)
                    notional = this_qty * fill_px
                    fee = notional * maker_rate
                    if this_qty > QTY_EPS:
                        cash += notional - fee
                        pos_qty -= this_qty
                        fills.append({
                            "ts": idx[i], "side": "sell", "size": this_qty,
                            "price": fill_px, "fee": fee, "is_maker": True,
                            "slippage_bps": float(execution.queue_position_penalty_bps),
                            "order_id": f"L{active['posted_idx']}-sell",
                            "parent_signal_ts": idx[active["posted_idx"]],
                        })
                        if active_trade is not None:
                            if this_qty >= active_trade["qty"] - QTY_EPS:
                                pnl = (fill_px - active_trade["entry_price"]) * active_trade["qty"] \
                                      - active_trade["entry_fee"] - fee
                                trades.append({
                                    "entry_idx": active_trade["entry_idx"],
                                    "entry_price": active_trade["entry_price"],
                                    "qty": active_trade["qty"],
                                    "exit_idx": i, "exit_price": fill_px, "pnl": pnl,
                                })
                                active_trade = None
                            else:
                                portion = this_qty / active_trade["qty"]
                                entry_fee_portion = active_trade["entry_fee"] * portion
                                pnl = (fill_px - active_trade["entry_price"]) * this_qty \
                                      - entry_fee_portion - fee
                                trades.append({
                                    "entry_idx": active_trade["entry_idx"],
                                    "entry_price": active_trade["entry_price"],
                                    "qty": this_qty, "exit_idx": i,
                                    "exit_price": fill_px, "pnl": pnl,
                                })
                                active_trade["qty"] -= this_qty
                                active_trade["entry_fee"] -= entry_fee_portion
                        active["qty_remaining"] -= this_qty
                    if active["qty_remaining"] <= QTY_EPS or pos_qty <= QTY_EPS:
                        active = None
                        if pos_qty <= QTY_EPS:
                            tsl_peak_price = None

        # --- 2b) stop / tp check while in position. Stops override any
        #         resting exit limit: we assume the protective stop was
        #         always present as a parallel order in the book.
        if pos_qty > QTY_EPS and active_trade is not None:
            if tsl_peak_price is None or high_a[i] > tsl_peak_price:
                tsl_peak_price = high_a[i]

            stop_level = None; stop_reason = None
            if sl_stop is not None:
                stop_level = active_trade["entry_price"] * (1.0 - float(sl_stop))
                stop_reason = "sl_stop"
            elif tsl_stop is not None and tsl_peak_price is not None:
                stop_level = tsl_peak_price * (1.0 - float(tsl_stop))
                stop_reason = "tsl_stop"

            tp_level = None
            if tp_stop is not None:
                tp_level = active_trade["entry_price"] * (1.0 + float(tp_stop))

            trigger_stop = stop_level is not None and low_a[i] <= stop_level
            trigger_tp   = tp_level   is not None and high_a[i] >= tp_level
            if trigger_stop:
                exit_px = stop_level * (1.0 - slip); exit_reason = stop_reason
            elif trigger_tp:
                exit_px = tp_level * (1.0 - slip); exit_reason = "tp_stop"
            else:
                exit_px = None; exit_reason = None

            if exit_px is not None:
                # Cancel any resting sell limit first.
                if active is not None and active["side"] == "sell":
                    unfilled.append({
                        "ts_posted": idx[active["posted_idx"]],
                        "side": active["side"],
                        "limit_price": active["L"],
                        "expired_at": idx[i],
                        "reason": "stop_override",
                    })
                    active = None
                qty_close = pos_qty
                notional = qty_close * exit_px
                fee = notional * taker_rate
                cash += notional - fee
                pos_qty = 0.0
                fills.append({
                    "ts": idx[i], "side": "sell", "size": qty_close,
                    "price": exit_px, "fee": fee, "is_maker": False,
                    "slippage_bps": float(execution.slippage_bps),
                    "order_id": f"S{i}-{exit_reason}",
                    "parent_signal_ts": idx[active_trade["entry_idx"]],
                })
                pnl = (exit_px - active_trade["entry_price"]) * qty_close \
                      - active_trade["entry_fee"] - fee
                trades.append({
                    "entry_idx": active_trade["entry_idx"],
                    "entry_price": active_trade["entry_price"],
                    "qty": qty_close, "exit_idx": i,
                    "exit_price": exit_px, "pnl": pnl,
                    "exit_reason": exit_reason,
                })
                active_trade = None
                tsl_peak_price = None

        # --- 3) new signal on bar i → post resting order
        if entry_a[i] and pos_qty == 0.0 and active is None:
            L = close_a[i] * (1.0 - execution.limit_offset_pct)
            target_qty = cash / (L * (1.0 + maker_rate)) if L > 0 else 0.0
            active = {
                "side": "buy", "L": L, "qty_remaining": target_qty,
                "initial_qty": target_qty, "posted_idx": i,
                "expires_at_idx": i + 1 + execution.limit_valid_bars,
            }
        elif exit_a[i] and pos_qty > 0.0 and active is None:
            L = close_a[i] * (1.0 + execution.limit_offset_pct)
            target_qty = pos_qty
            active = {
                "side": "sell", "L": L, "qty_remaining": target_qty,
                "initial_qty": target_qty, "posted_idx": i,
                "expires_at_idx": i + 1 + execution.limit_valid_bars,
            }

        # --- 4) mark-to-market equity
        equity[i] = cash + pos_qty * close_a[i]

    # dangling active order at end
    if active is not None:
        unfilled.append({
            "ts_posted": idx[active["posted_idx"]], "side": active["side"],
            "limit_price": active["L"], "expired_at": idx[-1],
            "reason": "session_end",
        })

    fills_df = (pd.DataFrame(fills, columns=_empty_fills_df().columns)
                if fills else _empty_fills_df())
    unfilled_df = (pd.DataFrame(unfilled, columns=_empty_unfilled_df().columns)
                   if unfilled else _empty_unfilled_df())

    equity_series = pd.Series(equity, index=idx, name="equity")
    metrics = _metrics_from_equity(equity_series, trades, label, init_cash)
    gross_pnl = (metrics["final_equity"] - init_cash) + float(fills_df["fee"].sum()) \
                if len(fills_df) else (metrics["final_equity"] - init_cash)
    exec_metrics = _build_execution_metrics(fills_df, unfilled_df,
                                            gross_pnl=gross_pnl, mode="limit")

    # Attach the equity series so callers can recover .value()-style usage
    # without a vbt Portfolio.
    result = BacktestResult(
        pf=None, metrics=metrics, fills=fills_df,
        unfilled_orders=unfilled_df, execution_metrics=exec_metrics,
    )
    result.equity = equity_series  # type: ignore[attr-defined]
    return result


# ---------------------------------------------------------------------
# Combine per-asset backtests into a portfolio report
# ---------------------------------------------------------------------
def combined_equity(per_asset_pfs: dict,
                    allocation: dict = PORTFOLIO_ALLOC,
                    total: float = TOTAL_CAPITAL) -> pd.DataFrame:
    """
    Scale each per-asset equity curve by its allocation weight × total,
    then sum. Returns a tidy DataFrame with dt index and 'portfolio_equity'.
    """
    scaled = []
    for sym, pf in per_asset_pfs.items():
        w = allocation.get(sym, 0.0)
        if w == 0:
            continue
        eq = pf.value().copy()
        # Rebase each curve to 1.0, then scale by allocation × total.
        eq = eq / eq.iloc[0] * (w * total)
        scaled.append(eq.rename(sym))

    port = pd.concat(scaled, axis=1).ffill().fillna(method="bfill")
    port["portfolio_equity"] = port.sum(axis=1)
    return port


def portfolio_metrics(port_eq: pd.Series,
                      total_capital: float = TOTAL_CAPITAL) -> dict:
    """
    Compute CAGR, Sharpe, Sortino, MaxDD, Calmar from a combined equity curve.
    """
    eq = port_eq.dropna()
    if len(eq) < 2:
        return dict(cagr=0, sharpe=0, sortino=0, max_dd=0, calmar=0, final=0, total_return=0)

    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    total_ret = eq.iloc[-1] / eq.iloc[0] - 1.0
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1.0 / max(years, 1e-6)) - 1.0

    rets = eq.pct_change().dropna()
    # Sharpe, annualised. Bar freq inferred from median dt.
    dt = rets.index.to_series().diff().median()
    bars_per_year = pd.Timedelta(days=365.25) / dt if dt else 1
    mu, sd = rets.mean(), rets.std()
    sharpe = (mu / sd) * np.sqrt(bars_per_year) if sd > 0 else 0.0
    dn = rets[rets < 0].std()
    sortino = (mu / dn) * np.sqrt(bars_per_year) if dn > 0 else 0.0

    peak = eq.cummax()
    dd = (eq / peak - 1.0)
    max_dd = float(dd.min())
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0

    return dict(
        total_return=float(total_ret),
        cagr=float(cagr),
        sharpe=float(sharpe),
        sortino=float(sortino),
        max_dd=float(max_dd),
        calmar=float(calmar),
        final=float(eq.iloc[-1]),
    )


# ---------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------
def walk_forward_splits(index: pd.DatetimeIndex,
                        train_years: int = 2,
                        test_years: int = 1) -> list[tuple]:
    """
    Anchored walk-forward: train on [t0..t0+train], test on [train..train+test],
    step forward by test_years.
    Returns list of (train_slice, test_slice) datetime pairs.
    """
    out = []
    start = index[0]
    end = index[-1]
    cur = start
    while True:
        train_end = cur + pd.DateOffset(years=train_years)
        test_end  = train_end + pd.DateOffset(years=test_years)
        if test_end > end:
            break
        out.append(((cur, train_end), (train_end, test_end)))
        cur = cur + pd.DateOffset(years=test_years)
    return out


# ---------------------------------------------------------------------
# Syntax sanity: run-on-import self-check
# ---------------------------------------------------------------------
if __name__ == "__main__":
    df = load("BTCUSDT", "1d", "2022-01-01", "2024-01-01")
    print(f"loaded {len(df)} bars  {df.index.min()} → {df.index.max()}")
    fast = df["close"].rolling(20).mean()
    slow = df["close"].rolling(50).mean()
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    res = run_backtest(df, entries, exits, label="smoke-test-20/50 SMA")
    for k, v in res.metrics.items():
        print(f"  {k:15s} {v}")
