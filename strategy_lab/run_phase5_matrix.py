"""
Phase 5 — backtest matrix driver.

Grid:
    A1 (regime_switcher)          on BTC/ETH/SOL @ 4h, 2022-01 -> 2024-12
    B1 (kama_adaptive_trend)      on BTC/ETH/SOL @ 1h, 2022-01 -> 2024-12
    D1 (htf_regime_ltf_pullback)  on BTC/ETH/SOL @ 15m (HTF=4h), 2023-06 -> 2024-12

Runs each cell, computes the full metric suite, saves one CSV per run +
a consolidated summary CSV, and prints a compact table to stdout.

No Optuna / walk-forward in V1 — hand-tuned defaults from the candidate
specs. Walk-forward + parameter plateau are Phase 5.5 (robustness battery).
Correlation vs existing book is computed against buy-and-hold equity as a
coarse proxy; full-book correlation awaits Phase 1 v2 regeneration.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine  # noqa: E402
from strategies.adaptive import (  # noqa: E402
    a1_generate_signals, b1_generate_signals,
    c1_generate_signals, d1_generate_signals,
)
from regime import classify_regime, REGIME_4H_PRESET  # noqa: E402
import eval as ev  # noqa: E402

EQUITY_DIR = REPO / "docs" / "research" / "phase5_results" / "equity_curves"
EQUITY_DIR.mkdir(parents=True, exist_ok=True)


def _trade_stats_from_pf(res) -> dict:
    """Extract win_rate / profit_factor / avg_win / avg_loss / avg_hold from the backtest result."""
    out = {"win_rate": 0.0, "profit_factor": 0.0, "avg_win": 0.0,
           "avg_loss": 0.0, "avg_hold_bars": 0.0}
    # Limit-mode path stashes records on res.metrics
    m = res.metrics or {}
    out["win_rate"]      = float(m.get("win_rate", 0.0) or 0.0)
    out["profit_factor"] = float(m.get("profit_factor", 0.0) or 0.0)
    out["avg_win"]       = float(m.get("avg_win", 0.0) or 0.0)
    out["avg_loss"]      = float(m.get("avg_loss", 0.0) or 0.0)
    # vbt path — prefer its trade records when available
    pf = getattr(res, "pf", None)
    if pf is not None:
        try:
            tr = pf.trades.records_readable
            if tr is not None and len(tr) > 0:
                pnls = tr.get("PnL", tr.get("Pnl"))
                if pnls is not None:
                    wins = (pnls > 0).sum()
                    out["win_rate"] = float(wins / len(pnls))
                    gross_win  = float(pnls[pnls > 0].sum())
                    gross_loss = float(-pnls[pnls < 0].sum())
                    out["profit_factor"] = gross_win / gross_loss if gross_loss > 0 else 0.0
                    out["avg_win"]  = float(pnls[pnls > 0].mean()) if wins else 0.0
                    out["avg_loss"] = float(pnls[pnls < 0].mean()) if wins < len(pnls) else 0.0
                # hold duration
                ent_ts = tr.get("Entry Timestamp", tr.get("Entry Date"))
                ext_ts = tr.get("Exit Timestamp",  tr.get("Exit Date"))
                if ent_ts is not None and ext_ts is not None and len(ent_ts) > 0:
                    durs = (pd.to_datetime(ext_ts) - pd.to_datetime(ent_ts))
                    out["avg_hold_bars"] = float(durs.mean().total_seconds() / 3600)
        except Exception:
            pass
    return out


def _yearly_returns(equity: pd.Series) -> dict:
    """Yearly compound returns keyed by year string."""
    if equity is None or len(equity) < 2:
        return {}
    yr = equity.resample("YE").last()
    yr0 = pd.concat([equity.iloc[:1], yr])
    ret = yr0.pct_change().dropna()
    return {str(idx.year): round(float(v), 4) for idx, v in ret.items()}


def _monthly_returns(equity: pd.Series) -> dict:
    """Monthly compound returns keyed by YYYY-MM."""
    if equity is None or len(equity) < 2:
        return {}
    m = equity.resample("ME").last()
    m0 = pd.concat([equity.iloc[:1], m])
    ret = m0.pct_change().dropna()
    return {f"{idx.year:04d}-{idx.month:02d}": round(float(v), 4) for idx, v in ret.items()}


# ---------------------------------------------------------------------
# Matrix spec
# ---------------------------------------------------------------------
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
OUTPUT_DIR = REPO / "docs" / "research" / "phase5_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# bars-per-year for Sharpe annualization
BARS_PER_YEAR = {
    "15m": 365.25 * 96,
    "30m": 365.25 * 48,
    "1h":  365.25 * 24,
    "4h":  365.25 * 6,
    "1d":  365.25,
}


# ---------------------------------------------------------------------
# Per-run scoring
# ---------------------------------------------------------------------
def score_run(
    strategy_id: str, symbol: str, tf: str,
    df: pd.DataFrame, res, regime_df: pd.DataFrame | None,
    n_trials_for_dsr: int,
) -> dict[str, Any]:
    """
    Compute the full metric suite for one backtest run.
    """
    ppy = BARS_PER_YEAR.get(tf, 2190.0)
    equity = getattr(res, "equity", None)
    if equity is None and res.pf is not None:
        equity = res.pf.value()
    if equity is None or len(equity) < 2:
        return {
            "strategy_id": strategy_id, "symbol": symbol, "tf": tf,
            "n_bars": len(df), "status": "no_equity", "n_trades": 0,
        }

    # IS / OOS split — 75/25
    split_idx = int(len(equity) * 0.75)
    is_eq  = equity.iloc[:split_idx]
    oos_eq = equity.iloc[split_idx:]
    is_ret  = is_eq.pct_change().dropna()
    oos_ret = oos_eq.pct_change().dropna()

    sharpe_is  = ev.sharpe_ratio(is_ret, ppy)
    sharpe_oos = ev.sharpe_ratio(oos_ret, ppy)
    sortino_oos = ev.sortino_ratio(oos_ret, ppy)

    total_oos = float(oos_eq.iloc[-1] / oos_eq.iloc[0]) - 1.0
    years_oos = len(oos_eq) / ppy
    cagr_oos = (1 + total_oos) ** (1.0 / years_oos) - 1.0 if years_oos > 0 else 0.0
    mdd_oos = ev.max_drawdown(oos_eq)
    calmar_oos = ev.calmar_ratio(cagr_oos, mdd_oos)
    ulcer_oos = ev.ulcer_index(oos_eq)
    upi_oos = ev.ulcer_performance_index(oos_eq, ppy)
    tail_oos = ev.tail_ratio(oos_ret)

    dd_dur = ev.dd_duration_bars(oos_eq)
    dd_rec = ev.dd_recovery_bars(oos_eq)

    # DSR — trial count = matrix size so far (conservative inflator)
    psr_oos = ev.probabilistic_sharpe(sharpe_oos, n_obs=len(oos_ret))
    dsr_oos = ev.deflated_sharpe(
        sharpe_oos, n_obs=len(oos_ret), n_trials=n_trials_for_dsr,
        sd_sharpe_trials=1.0,
    )

    # Regime-conditional Sharpe (on OOS bars only, using regime_df aligned)
    regime_sharpes = {}
    n_profitable_regimes = 0
    if regime_df is not None:
        oos_labels = regime_df["label"].reindex(oos_ret.index).astype(str)
        regime_sharpes = ev.regime_conditional_sharpe(oos_ret, oos_labels, ppy)
        n_profitable_regimes = sum(1 for s in regime_sharpes.values() if s > 0)

    # Monthly return distribution on OOS
    m_ret = ev.monthly_returns(oos_eq)
    worst3_mean = float(m_ret.sort_values().head(3).mean()) if len(m_ret) >= 3 else 0.0

    # Correlation vs buy-and-hold on the overlapping OOS window (proxy for
    # existing-book correlation — real book-correlation is a Phase 1 v2 follow-up).
    close_oos = df["close"].reindex(oos_eq.index)
    bh_ret = close_oos.pct_change().dropna()
    common = oos_ret.reindex(bh_ret.index).dropna()
    bh_aligned = bh_ret.reindex(common.index)
    if len(common) >= 30 and bh_aligned.std() > 0 and common.std() > 0:
        rho_bh = float(np.corrcoef(common.values, bh_aligned.values)[0, 1])
    else:
        rho_bh = 0.0

    exec_m = res.execution_metrics or {}

    # Persist the equity curve for the dashboard.
    eq_path = EQUITY_DIR / f"{strategy_id}__{symbol}__{tf}.parquet"
    try:
        equity.to_frame(name="equity").to_parquet(eq_path)
    except Exception:
        pass

    # Extra per-cell stats the dashboard needs.
    trade_stats = _trade_stats_from_pf(res)
    monthly = _monthly_returns(equity)
    yearly = _yearly_returns(equity)

    def _num(key, default=0.0):
        """Coerce None to default for metrics that sometimes return None."""
        v = exec_m.get(key, default)
        return default if v is None else v

    # Hard-gate checks
    gates = {
        "gate_mdd":           mdd_oos > -0.20,
        "gate_calmar":        calmar_oos > 1.5,
        "gate_dsr":           dsr_oos > 1.0,      # DSR returns prob [0,1]; use >0.5 below
        "gate_dsr_prob":      dsr_oos > 0.95,    # stricter — 95% prob edge isn't trial-mined
        "gate_regimes":       n_profitable_regimes >= 2,
        "gate_rho_to_bh":     abs(rho_bh) < 0.5,
        "gate_maker_fill":    _num("maker_fill_pct") >= 0.60,
    }
    gates_passed = sum(gates.values())

    return {
        "strategy_id": strategy_id, "symbol": symbol, "tf": tf,
        "n_bars": len(df), "n_trades": int(res.metrics.get("n_trades", 0)),
        "is_sharpe": round(sharpe_is, 3),
        "oos_sharpe": round(sharpe_oos, 3),
        "oos_sortino": round(sortino_oos, 3),
        "oos_cagr": round(cagr_oos, 4),
        "oos_max_dd": round(mdd_oos, 4),
        "oos_calmar": round(calmar_oos, 3),
        "oos_ulcer": round(ulcer_oos, 3),
        "oos_upi": round(upi_oos, 3),
        "oos_tail_ratio": round(tail_oos, 3),
        "oos_dd_duration_bars": dd_dur,
        "oos_dd_recovery_bars": dd_rec,
        "oos_psr": round(psr_oos, 4),
        "oos_dsr": round(dsr_oos, 4),
        "n_profitable_regimes": n_profitable_regimes,
        "regime_sharpes": regime_sharpes,
        "worst3_months_mean": round(worst3_mean, 4),
        "rho_buy_hold_oos": round(rho_bh, 3),
        "maker_fill_pct": round(_num("maker_fill_pct"), 3),
        "unfilled_pct":   round(_num("unfilled_order_pct"), 3),
        "fee_drag":       exec_m.get("fee_drag_pct_of_pnl"),
        "total_fee_paid": round(_num("total_fee_paid"), 2),
        "gates_passed": gates_passed,
        "gate_detail": gates,
        # Trade stats
        "win_rate":       round(trade_stats["win_rate"], 3),
        "profit_factor":  round(trade_stats["profit_factor"], 3),
        "avg_win":        round(trade_stats["avg_win"], 2),
        "avg_loss":       round(trade_stats["avg_loss"], 2),
        "avg_hold_bars":  round(trade_stats["avg_hold_bars"], 2),
        # Time-bucketed returns (dicts; will be flattened in dashboard)
        "monthly_returns": monthly,
        "yearly_returns":  yearly,
        # Equity curve file
        "equity_file": str(eq_path.name),
    }


# ---------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------
def run_a1(symbol: str):
    df = engine.load(symbol, "4h", start="2022-01-01", end="2024-12-31")
    # V3: tighter SL on ETH/SOL (noisier regime classifier).
    sl_mult = 3.0 if symbol == "BTCUSDT" else 4.0
    sig = a1_generate_signals(df, sl_atr_mult=sl_mult)
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot",
        limit_valid_bars=3, limit_offset_pct=0.0,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=0.2,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(
        df, entries=sig["entries"], exits=sig["exits"],
        sl_stop=sig["_meta"]["atr_pct_suggested_sl"],
        execution=cfg,
    )
    regime_df = classify_regime(df, config=REGIME_4H_PRESET)
    return df, res, regime_df


def run_b1(symbol: str):
    df = engine.load(symbol, "1h", start="2022-01-01", end="2024-12-31")
    sig = b1_generate_signals(df)
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot",
        limit_valid_bars=3, limit_offset_pct=0.0,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=0.2,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(
        df, entries=sig["entries"], exits=sig["exits"],
        tsl_stop=sig["_meta"]["atr_pct_suggested_tsl"],
        execution=cfg,
    )
    regime_df = classify_regime(df, config=REGIME_4H_PRESET)
    return df, res, regime_df


def run_d1(symbol: str):
    df_15m = engine.load(symbol, "15m", start="2023-06-01", end="2024-12-31")
    df_4h  = engine.load(symbol, "4h",  start="2023-06-01", end="2024-12-31")
    # V3 symbol-specific: ETH/SOL need looser filters to accumulate trades.
    # BTC keeps the strict V2 stack that produced +0.47 Sharpe / -2.3% MDD.
    if symbol == "BTCUSDT":
        sig = d1_generate_signals(df_15m, df_4h=df_4h)
    else:
        sig = d1_generate_signals(
            df_15m, df_4h=df_4h,
            rsi_threshold=8.0,
            require_bullish_reversal=False,
        )
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot",
        limit_valid_bars=2, limit_offset_pct=0.0,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=0.2,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(
        df_15m, entries=sig["entries"], exits=sig["exits"],
        sl_stop=sig["_meta"]["atr_pct_suggested_sl"],
        tp_stop=sig["_meta"]["atr_pct_suggested_tp"],
        execution=cfg,
    )
    # Use the 4h regime to score regime-conditional (forward-filled to 15m)
    from strategies.adaptive.common import align_htf_regime_to_ltf
    regime_4h = classify_regime(df_4h, config=REGIME_4H_PRESET)
    regime_ltf = align_htf_regime_to_ltf(df_15m, regime_4h, htf_close_lag_bars=1)
    return df_15m, res, regime_ltf


def run_c1(symbol: str):
    df = engine.load(symbol, "4h", start="2022-01-01", end="2024-12-31")
    from strategies.adaptive.c1_meta_labeled_donchian import generate_signals as c1_gen
    sig = c1_gen(df)
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot",
        limit_valid_bars=3, limit_offset_pct=0.0,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=0.2,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(
        df, entries=sig["entries"], exits=sig["exits"],
        sl_stop=sig["_meta"]["atr_pct_suggested_sl"],
        tp_stop=sig["_meta"]["atr_pct_suggested_tp"],
        execution=cfg,
    )
    regime_df = classify_regime(df, config=REGIME_4H_PRESET)
    return df, res, regime_df


RUNNERS = {
    "a1_regime_switcher":         ("4h",  run_a1),
    "b1_kama_adaptive_trend":     ("1h",  run_b1),
    "c1_meta_labeled_donchian":   ("4h",  run_c1),
    "d1_htf_regime_ltf_pullback": ("15m", run_d1),
}


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--strategies", nargs="+",
                        default=list(RUNNERS.keys()))
    args = parser.parse_args(argv)

    rows = []
    total_cells = len(args.symbols) * len(args.strategies)
    n_trials_for_dsr = max(total_cells, 10)

    cell = 0
    for strategy_id in args.strategies:
        tf, runner = RUNNERS[strategy_id]
        for symbol in args.symbols:
            cell += 1
            print(f"[{cell}/{total_cells}] {strategy_id} on {symbol} @ {tf} ... ",
                  end="", flush=True)
            try:
                df, res, regime_df = runner(symbol)
                row = score_run(strategy_id, symbol, tf, df, res, regime_df,
                                n_trials_for_dsr)
                rows.append(row)
                print(f"n_trades={row['n_trades']:>3} | "
                      f"Sharpe_oos={row['oos_sharpe']:>5.2f} | "
                      f"Calmar={row['oos_calmar']:>5.2f} | "
                      f"MDD={row['oos_max_dd']*100:>6.1f}% | "
                      f"gates_passed={row['gates_passed']}/7")
            except Exception as e:
                print(f"ERROR: {type(e).__name__}: {e}")
                rows.append({"strategy_id": strategy_id, "symbol": symbol,
                             "tf": tf, "status": f"error: {e}"})

    df_out = pd.DataFrame(rows)
    # Drop nested dicts for the CSV — they're re-serialized as JSON columns
    # so the dashboard can re-parse them per cell.
    import json
    for col in ("regime_sharpes", "gate_detail", "monthly_returns", "yearly_returns"):
        if col in df_out.columns:
            df_out[col] = df_out[col].apply(
                lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v
            )
    csv_path = OUTPUT_DIR / "phase5_matrix_results.csv"
    df_out.to_csv(csv_path, index=False)
    print(f"\nResults CSV: {csv_path}")

    # Short summary to stdout
    print("\n=========  PHASE 5 SUMMARY  =========")
    if "gates_passed" in df_out.columns:
        promoted = df_out[df_out["gates_passed"] >= 5]
        print(f"cells run:            {len(df_out)}")
        print(f"no-error cells:       {(df_out.get('status', 'ok') == 'ok').sum() if 'status' in df_out else len(df_out)}")
        print(f"cells passing >=5/7 gates: {len(promoted)}")
        for _, r in df_out.iterrows():
            print(f"  {r['strategy_id']:<32} {r['symbol']:>7} "
                  f"{r.get('tf',''):>4} | Sharpe_oos={r.get('oos_sharpe',0):+5.2f} "
                  f"Calmar={r.get('oos_calmar',0):+5.2f} "
                  f"MDD={r.get('oos_max_dd',0)*100:+6.1f}% "
                  f"Maker={r.get('maker_fill_pct',0):>5.1%} "
                  f"gates={r.get('gates_passed',0)}/7")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
