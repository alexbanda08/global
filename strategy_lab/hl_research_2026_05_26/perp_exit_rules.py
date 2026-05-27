"""
Perp-native exit rule helpers for Hyperliquid backtests.

These are the EXIT rules that distinguish perpetual futures trading from
fixed-window binary markets. They take (klines, fill, ...) and return the
exit timestamp (microseconds) and exit reason.

All exits are CAUSAL — only use bars at-or-after the fill timestamp.
"""
from __future__ import annotations
from typing import Literal
import numpy as np
import pandas as pd


def signal_flip_exit(
    klines: pd.DataFrame,
    signal_series: pd.Series,
    entry_idx: int,
    direction: Literal["LONG", "SHORT"],
) -> tuple[int, str]:
    """Exit when signal series flips to opposite direction.

    signal_series: a series aligned to klines.index with values
                   {+1=LONG, -1=SHORT, 0=neutral}.
    entry_idx: row index in klines where we entered.
    direction: position direction.
    Returns (exit_us, reason). If never flips, exits at last bar.
    """
    target_flip = -1 if direction == "LONG" else +1
    # Look at bars STRICTLY AFTER entry
    fwd = signal_series.iloc[entry_idx + 1 :]
    flip_mask = (fwd == target_flip) | (fwd == 0)
    if flip_mask.any():
        first_flip_idx = flip_mask.idxmax()
        exit_us = klines.loc[first_flip_idx, "open_time_us"] if "open_time_us" in klines else int(klines.loc[first_flip_idx].name.timestamp() * 1_000_000)
        return int(exit_us), "signal_flip"
    # Fall through: exit at last bar
    last_idx = klines.index[-1]
    exit_us = klines.loc[last_idx, "open_time_us"] if "open_time_us" in klines else int(last_idx.timestamp() * 1_000_000)
    return int(exit_us), "end_of_data"


def atr_trailing_stop_exit(
    klines: pd.DataFrame,
    entry_idx: int,
    entry_price: float,
    direction: Literal["LONG", "SHORT"],
    atr_series: pd.Series,
    atr_mult: float = 2.0,
    max_bars: int = 500,
) -> tuple[int, str]:
    """Trailing stop at `atr_mult * ATR` from running max (LONG) / min (SHORT)."""
    fwd = klines.iloc[entry_idx + 1 : entry_idx + 1 + max_bars]
    if len(fwd) == 0:
        last_idx = klines.index[-1]
        return _ts_us(klines, last_idx), "end_of_data"
    atr_fwd = atr_series.iloc[entry_idx + 1 : entry_idx + 1 + max_bars].fillna(method="ffill").fillna(method="bfill")

    if direction == "LONG":
        # Trail = running max high - atr_mult * ATR
        running_max = fwd["high"].cummax()
        trail = running_max - atr_mult * atr_fwd.values
        # Exit when low <= trail
        hit = fwd["low"].values <= trail.values
        if hit.any():
            first = int(np.argmax(hit))
            exit_idx = fwd.index[first]
            return _ts_us(klines, exit_idx), "atr_trail"
    else:  # SHORT
        running_min = fwd["low"].cummin()
        trail = running_min + atr_mult * atr_fwd.values
        hit = fwd["high"].values >= trail.values
        if hit.any():
            first = int(np.argmax(hit))
            exit_idx = fwd.index[first]
            return _ts_us(klines, exit_idx), "atr_trail"
    # No hit within max_bars
    last_idx = fwd.index[-1]
    return _ts_us(klines, last_idx), "max_bars"


def atr_sl_tp_exit(
    klines: pd.DataFrame,
    entry_idx: int,
    entry_price: float,
    direction: Literal["LONG", "SHORT"],
    atr_series: pd.Series,
    sl_mult: float = 1.0,
    tp_mult: float = 2.0,
    max_bars: int = 200,
) -> tuple[int, str]:
    """Bracket exit: stop-loss at sl_mult*ATR adverse, take-profit at tp_mult*ATR favorable."""
    fwd = klines.iloc[entry_idx + 1 : entry_idx + 1 + max_bars]
    if len(fwd) == 0:
        last_idx = klines.index[-1]
        return _ts_us(klines, last_idx), "end_of_data"
    # Use ATR at entry bar (fixed bracket, not dynamic)
    atr_at_entry = atr_series.iloc[entry_idx]
    if pd.isna(atr_at_entry) or atr_at_entry == 0:
        last_idx = fwd.index[-1]
        return _ts_us(klines, last_idx), "atr_nan"

    if direction == "LONG":
        sl_px = entry_price - sl_mult * atr_at_entry
        tp_px = entry_price + tp_mult * atr_at_entry
        sl_hit = fwd["low"].values <= sl_px
        tp_hit = fwd["high"].values >= tp_px
    else:
        sl_px = entry_price + sl_mult * atr_at_entry
        tp_px = entry_price - tp_mult * atr_at_entry
        sl_hit = fwd["high"].values >= sl_px
        tp_hit = fwd["low"].values <= tp_px

    sl_first = int(np.argmax(sl_hit)) if sl_hit.any() else -1
    tp_first = int(np.argmax(tp_hit)) if tp_hit.any() else -1

    if sl_first < 0 and tp_first < 0:
        return _ts_us(klines, fwd.index[-1]), "max_bars"
    if sl_first < 0:
        return _ts_us(klines, fwd.index[tp_first]), "take_profit"
    if tp_first < 0:
        return _ts_us(klines, fwd.index[sl_first]), "stop_loss"
    # Both hit — assume worst case (SL hits first within bar — pessimistic)
    if sl_first <= tp_first:
        return _ts_us(klines, fwd.index[sl_first]), "stop_loss"
    return _ts_us(klines, fwd.index[tp_first]), "take_profit"


def vol_regime_change_exit(
    klines: pd.DataFrame,
    entry_idx: int,
    direction: Literal["LONG", "SHORT"],
    regime_series: pd.Series,
    max_bars: int = 200,
) -> tuple[int, str]:
    """Exit when regime label flips out of `entry_regime`."""
    entry_regime = regime_series.iloc[entry_idx]
    fwd = regime_series.iloc[entry_idx + 1 : entry_idx + 1 + max_bars]
    if len(fwd) == 0:
        last_idx = klines.index[-1]
        return _ts_us(klines, last_idx), "end_of_data"
    flip_mask = fwd != entry_regime
    if flip_mask.any():
        flip_idx = flip_mask.idxmax()
        return _ts_us(klines, flip_idx), "regime_change"
    return _ts_us(klines, fwd.index[-1]), "max_bars"


def fixed_bars_exit(
    klines: pd.DataFrame,
    entry_idx: int,
    n_bars: int,
) -> tuple[int, str]:
    """Simple fixed N-bar hold."""
    exit_idx_pos = min(entry_idx + n_bars, len(klines) - 1)
    exit_idx = klines.index[exit_idx_pos]
    return _ts_us(klines, exit_idx), f"fixed_{n_bars}b"


def _ts_us(klines: pd.DataFrame, idx) -> int:
    """Extract microsecond timestamp from a kline row by index label."""
    if "open_time_us" in klines.columns:
        return int(klines.loc[idx, "open_time_us"])
    if "time_period_start_us" in klines.columns:
        return int(klines.loc[idx, "time_period_start_us"])
    # Assume DatetimeIndex
    try:
        return int(idx.timestamp() * 1_000_000)
    except Exception:
        return int(pd.Timestamp(idx).timestamp() * 1_000_000)


# ------------- Convenience: run a strategy with mixed exits -------------

def run_strategy(
    klines: pd.DataFrame,
    funding: pd.DataFrame,
    signals: pd.Series,             # +1=LONG fire, -1=SHORT fire, 0=no fire
    atr_series: pd.Series | None = None,
    regime_series: pd.Series | None = None,
    exit_kind: Literal["signal_flip", "atr_trail", "atr_sl_tp", "regime_change", "fixed_bars"] = "signal_flip",
    exit_params: dict | None = None,
    asset: str = "BTC",
    notional_usd: float = 250.0,
    leverage: float = 1.0,
    cfg=None,                       # HyperliquidConfig from hl_engine
) -> pd.DataFrame:
    """
    Run a perp-native strategy with the chosen exit rule.

    Requires hl_engine.fill_at_kline and simulate_with_funding from
    strategy_lab/hl_research_2026_05_26/hl_engine.py.
    Returns a trades DataFrame.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from hl_engine import HyperliquidConfig, fill_at_kline, simulate_with_funding

    cfg = cfg or HyperliquidConfig()
    exit_params = exit_params or {}

    # Vectorize: find all fire indices (avoid overlap — only fire if flat)
    fire_idxs = signals[(signals == 1) | (signals == -1)].index
    trades = []
    in_position_until = -np.inf

    for fire_idx in fire_idxs:
        entry_idx_pos = klines.index.get_loc(fire_idx)
        if entry_idx_pos >= len(klines) - 1:
            continue
        fire_us = _ts_us(klines, fire_idx)
        if fire_us < in_position_until:
            continue  # overlap — skip
        direction = "LONG" if signals.loc[fire_idx] == 1 else "SHORT"

        fill = fill_at_kline(klines, asset, fire_us, direction, notional_usd, leverage, cfg)
        if fill is None:
            continue
        # Find effective entry idx (next bar after signal)
        eff_entry_idx_pos = entry_idx_pos + 1
        if eff_entry_idx_pos >= len(klines) - 1:
            continue

        # Determine exit
        if exit_kind == "signal_flip":
            exit_us, reason = signal_flip_exit(klines, signals, eff_entry_idx_pos, direction)
        elif exit_kind == "atr_trail":
            exit_us, reason = atr_trailing_stop_exit(
                klines, eff_entry_idx_pos, fill.entry_price, direction,
                atr_series, **exit_params,
            )
        elif exit_kind == "atr_sl_tp":
            exit_us, reason = atr_sl_tp_exit(
                klines, eff_entry_idx_pos, fill.entry_price, direction,
                atr_series, **exit_params,
            )
        elif exit_kind == "regime_change":
            exit_us, reason = vol_regime_change_exit(
                klines, eff_entry_idx_pos, direction, regime_series, **exit_params,
            )
        elif exit_kind == "fixed_bars":
            exit_us, reason = fixed_bars_exit(klines, eff_entry_idx_pos, **exit_params)
        else:
            raise ValueError(f"Unknown exit_kind: {exit_kind}")

        trade = simulate_with_funding(klines, funding, fill, exit_us, cfg)
        trades.append({
            "asset": asset,
            "direction": direction,
            "entry_us": fill.entry_us,
            "entry_price": fill.entry_price,
            "exit_us": trade.exit_us,
            "exit_price": trade.exit_price,
            "exit_reason": reason,
            "bars_held": trade.bars_held,
            "pnl_gross_usd": trade.pnl_gross_usd,
            "pnl_net_usd": trade.pnl_net_usd,
            "funding_paid_usd": trade.funding_paid_usd,
            "fee_paid_usd": fill.fee_paid_usd + trade.exit_fee_paid_usd,
            "leverage": leverage,
        })
        in_position_until = exit_us

    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame, annualization_bars_per_year: float = 365.25 * 24) -> dict:
    """Compute perp-native metrics."""
    if len(trades) == 0:
        return {"n_trades": 0}
    pnl = trades["pnl_net_usd"]
    wins = (pnl > 0).sum()
    losses = (pnl < 0).sum()
    avg_win = pnl[pnl > 0].mean() if wins > 0 else 0
    avg_loss = pnl[pnl < 0].mean() if losses > 0 else 0
    pf = abs(pnl[pnl > 0].sum() / pnl[pnl < 0].sum()) if losses > 0 else float("inf")
    total = pnl.sum()
    cum = pnl.cumsum()
    max_dd = (cum - cum.cummax()).min()
    # Sharpe by bar-held weighting (rough)
    sharpe = (pnl.mean() / pnl.std()) * np.sqrt(annualization_bars_per_year / max(1, trades["bars_held"].mean())) if pnl.std() > 0 else 0
    return {
        "n_trades": int(len(trades)),
        "n_wins": int(wins),
        "win_rate": wins / len(trades),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "profit_factor": float(pf),
        "total_pnl": float(total),
        "max_dd": float(max_dd),
        "sharpe_ann": float(sharpe),
        "avg_bars_held": float(trades["bars_held"].mean()),
        "avg_funding": float(trades["funding_paid_usd"].mean()),
        "avg_fees": float(trades["fee_paid_usd"].mean()),
        "calmar": float(total / abs(max_dd)) if max_dd != 0 else float("inf"),
    }


if __name__ == "__main__":
    print("perp_exit_rules.py — perp-native exit primitives + run_strategy + summarize")
    print("Imports OK.")
