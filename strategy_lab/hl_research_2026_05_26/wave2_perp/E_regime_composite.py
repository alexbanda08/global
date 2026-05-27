"""E — Regime composite (PERP-NATIVE rebuild).

Four perp-native variants where regime is a STRATEGY ROUTER / SIZING multiplier
(not a binary gate as in W2d):

  E1 — Markov-switching strategy router
       BULL+trending_up  → A2 (EMA stack crossover LONG)
       BEAR+trending_dn  → A2 SHORT
       SIDEWAYS/ranging  → B1 RSI mean-reversion (LONG<25 / SHORT>75)
       Exit: signal flip OR regime change.

  E2 — Vol-regime → leverage sizing on A3 ADX-gated trend
       low vol  (<33% pct): 2.0x leverage
       mid vol  (33-67%):   1.0x leverage
       high vol (>67%):     0.5x leverage
       Compare composite vs flat 1x base.

  E3 — Session-conditional strategy switch
       London (07-16 UTC) + NY (12-21 UTC) → A1 Donchian breakout
       Asia (23-08 UTC)                    → B1 RSI reversion

  E4 — Cyclops 3-axis as CONFIDENCE multiplier on A2 EMA crossover
       3-of-3 axes agree → 2x notional
       2-of-3 axes agree → 1x notional
       <2 axes           → skip

Universe : BTC, ETH, SOL
TFs      : 1h, 4h
Costs    : HL taker 4.5 bps each side + slip 3 bps + hourly funding accrual

Outputs:
  - E_results.csv (per-cell summary)
  - E_regime_composite.md (human-readable report)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from strategy_lab.hl_research_2026_05_26.hl_engine import (  # noqa: E402
    HyperliquidConfig,
    run_backtest,
)

PANEL_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2_perp"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Bar utilities                                                                #
# --------------------------------------------------------------------------- #

def _bar_us(tf: str) -> int:
    return {
        "5m": 5 * 60_000_000, "15m": 15 * 60_000_000,
        "1h": 60 * 60_000_000, "4h": 4 * 60 * 60_000_000,
        "1d": 24 * 60 * 60_000_000,
    }[tf]


def _bars_per_year(tf: str) -> float:
    return {"5m": 105120.0, "15m": 35040.0, "1h": 8760.0, "4h": 2190.0, "1d": 365.25}[tf]


# --------------------------------------------------------------------------- #
# Signal primitives (perp-native, vectorized)                                  #
# --------------------------------------------------------------------------- #

def _ema_stack_signal(panel: pd.DataFrame) -> np.ndarray:
    """A2-equivalent: EMA stack CROSSOVER (edge-triggered). +1 only at the bar
    where stack first reaches >=2 (rising from <2); -1 mirror. Subsequent bars
    return 0 even while stack remains elevated. This prevents firing every bar
    when the trend is persistent.
    """
    stack = panel["tr_ema_stack_score"].fillna(0).to_numpy()
    state = np.where(stack >= 2, 1, np.where(stack <= -2, -1, 0)).astype(np.int8)
    # edge-trigger: fire only when state != prev_state AND state != 0
    prev = np.roll(state, 1)
    prev[0] = 0
    edge_up = (state == 1) & (prev != 1)
    edge_dn = (state == -1) & (prev != -1)
    sig = np.where(edge_up, 1, np.where(edge_dn, -1, 0)).astype(np.int8)
    return sig


def _rsi_meanrev_signal(panel: pd.DataFrame, lo: float = 25.0, hi: float = 75.0) -> np.ndarray:
    """B1-equivalent edge-triggered: fire LONG only at the bar RSI first
    crosses BELOW `lo` (was >=lo, now <lo). Fire SHORT mirror. This prevents
    firing every bar while RSI is languishing in the extreme zone."""
    rsi = panel["rsi_14"].fillna(50).to_numpy()
    prev = np.roll(rsi, 1)
    prev[0] = 50.0
    cross_lo = (rsi < lo) & (prev >= lo)
    cross_hi = (rsi > hi) & (prev <= hi)
    return np.where(cross_lo, 1, np.where(cross_hi, -1, 0)).astype(np.int8)


def _donchian_breakout_signal(panel: pd.DataFrame, lookback: int = 20) -> np.ndarray:
    """A1-equivalent: Donchian breakout — long if close>rolling_max(n-1) of high,
    short if close<rolling_min(n-1) of low. Uses prior-bar window to avoid lookahead.
    """
    high = panel["high"].to_numpy(dtype=float)
    low = panel["low"].to_numpy(dtype=float)
    close = panel["close"].to_numpy(dtype=float)
    n = close.size
    sig = np.zeros(n, dtype=np.int8)
    if n < lookback + 1:
        return sig
    # rolling max of high[0..i-1], i.e., shift by 1 so current bar doesn't see itself
    h_max = pd.Series(high).shift(1).rolling(lookback, min_periods=lookback).max().to_numpy()
    l_min = pd.Series(low).shift(1).rolling(lookback, min_periods=lookback).min().to_numpy()
    long_break = close > h_max
    short_break = close < l_min
    state = np.where(long_break, 1, np.where(short_break, -1, 0)).astype(np.int8)
    # Edge-trigger: fire only at the breakout bar
    prev = np.roll(state, 1)
    prev[0] = 0
    edge_up = (state == 1) & (prev != 1)
    edge_dn = (state == -1) & (prev != -1)
    return np.where(edge_up, 1, np.where(edge_dn, -1, 0)).astype(np.int8)


def _adx_trend_signal(panel: pd.DataFrame, adx_thresh: float = 20.0) -> np.ndarray:
    """A3-equivalent edge-triggered: fire only at the bar where the DI cross
    HAPPENS while adx>thresh. Prevents firing every bar in a trend."""
    adx = panel["adx_14"].fillna(0).to_numpy()
    plus = panel["plus_di_14"].fillna(0).to_numpy()
    minus = panel["minus_di_14"].fillna(0).to_numpy()
    state = np.where((adx > adx_thresh) & (plus > minus), 1,
                     np.where((adx > adx_thresh) & (minus > plus), -1, 0)).astype(np.int8)
    prev = np.roll(state, 1)
    prev[0] = 0
    edge_up = (state == 1) & (prev != 1)
    edge_dn = (state == -1) & (prev != -1)
    return np.where(edge_up, 1, np.where(edge_dn, -1, 0)).astype(np.int8)


# --------------------------------------------------------------------------- #
# Cyclops 3-axis votes (ported from W2d, used by E4)                           #
# --------------------------------------------------------------------------- #

def _lr_slope_sign(close: np.ndarray, k: int = 20, eps_frac: float = 5e-4) -> np.ndarray:
    n = close.size
    out = np.zeros(n, dtype=np.int8)
    if n < k:
        return out
    x = np.arange(k, dtype=np.float64)
    xm = x.mean()
    denom = ((x - xm) ** 2).sum()
    if denom <= 0:
        return out
    win = np.lib.stride_tricks.sliding_window_view(close, k)
    ym = win.mean(axis=1)
    numer = ((x - xm)[None, :] * (win - ym[:, None])).sum(axis=1)
    slope = numer / denom
    frac = slope * k / np.where(ym > 0, ym, np.nan)
    sign = np.where(frac > eps_frac, 1, np.where(frac < -eps_frac, -1, 0))
    out[k - 1:] = sign.astype(np.int8)
    return out


def _cyclops_axes(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    close = panel["close"].to_numpy(dtype=float)
    slope_sign = _lr_slope_sign(close, k=20)
    stack = panel["tr_ema_stack_score"].fillna(0).to_numpy()
    stack_sign = np.where(stack >= 1, 1, np.where(stack <= -1, -1, 0))
    trend_v = np.where((slope_sign == 1) & (stack_sign == 1), 1,
                      np.where((slope_sign == -1) & (stack_sign == -1), -1, 0)).astype(np.int8)

    # LEVELS
    atr = panel["atr_14"].fillna(0).to_numpy()
    p_hi = panel["pivot_high"].ffill().to_numpy()
    p_lo = panel["pivot_low"].ffill().to_numpy()
    bos_buy_3 = panel["bos_buy"].fillna(0).rolling(3, min_periods=1).sum().to_numpy()
    bos_sell_3 = panel["bos_sell"].fillna(0).rolling(3, min_periods=1).sum().to_numpy()
    safe_atr = np.where(atr > 0, atr, np.nan)
    dist_to_lo = np.where(p_lo > 0, (close - p_lo) / safe_atr, np.nan)
    dist_to_hi = np.where(p_hi > 0, (p_hi - close) / safe_atr, np.nan)
    near_support = (dist_to_lo >= 0) & (dist_to_lo <= 0.5) & (bos_sell_3 == 0)
    near_resist = (dist_to_hi >= 0) & (dist_to_hi <= 0.5) & (bos_buy_3 == 0)
    levels_v = np.where(near_support, 1, np.where(near_resist, -1, 0)).astype(np.int8)

    # MOMENTUM (rsi + markov non-conflict)
    rsi = panel["rsi_14"].fillna(50).to_numpy()
    mks = panel["markov_state_fixed"].fillna(0).to_numpy() if "markov_state_fixed" in panel.columns \
          else panel["markov_state"].fillna(0).to_numpy()
    momentum_v = np.where((rsi > 55) & (mks >= 0), 1,
                          np.where((rsi < 45) & (mks <= 0), -1, 0)).astype(np.int8)
    return trend_v, levels_v, momentum_v


# --------------------------------------------------------------------------- #
# Regime utilities                                                             #
# --------------------------------------------------------------------------- #

def _markov_int(panel: pd.DataFrame) -> np.ndarray:
    col = "markov_state_fixed" if "markov_state_fixed" in panel.columns else "markov_state"
    return panel[col].fillna(0).astype(int).to_numpy()


def _regime_label(panel: pd.DataFrame) -> np.ndarray:
    """Map to {-1: trending_dn, 0: ranging, +1: trending_up}."""
    rl = panel["regime_label"].fillna("ranging").to_numpy()
    out = np.zeros_like(rl, dtype=np.int8)
    out[rl == "trending_up"] = 1
    out[rl == "trending_dn"] = -1
    return out


def _vol_buckets(panel: pd.DataFrame, lookback: int = 60) -> np.ndarray:
    """Realized vol via rolling std of log-returns; bucket to low/mid/high
    using EXPANDING quantiles (causal, no peek)."""
    close = panel["close"].to_numpy(dtype=float)
    logret = np.log(close / np.maximum(np.roll(close, 1), 1e-12))
    logret[0] = 0
    rv = pd.Series(logret).rolling(lookback, min_periods=lookback).std().to_numpy()
    # Expanding quantiles (causal). For speed use pandas expanding.
    rv_ser = pd.Series(rv)
    q33 = rv_ser.expanding(min_periods=200).quantile(1/3).to_numpy()
    q67 = rv_ser.expanding(min_periods=200).quantile(2/3).to_numpy()
    out = np.full(len(rv), 1, dtype=np.int8)  # mid default
    low = rv < q33
    high = rv > q67
    out[low] = 0
    out[high] = 2
    # Mark warmup as mid so we don't trade with no quantile
    out[np.isnan(q33)] = 1
    return out


def _session_int(panel: pd.DataFrame) -> np.ndarray:
    """Session label: 0=Asia(23-08), 1=London(07-16), 2=NY(12-21). Overlap → NY wins
    (most relevant)."""
    ts = pd.to_datetime(panel["ts_us"], unit="us", utc=True)
    h = ts.dt.hour
    out = np.zeros(len(panel), dtype=np.int8)
    asia = (h >= 23) | (h < 8)
    london = (h >= 7) & (h < 16)
    ny = (h >= 12) & (h < 21)
    out[asia] = 0
    out[london] = 1
    out[ny] = 2  # NY takes precedence
    return out


# --------------------------------------------------------------------------- #
# E1 — Markov-switching strategy router                                        #
# --------------------------------------------------------------------------- #

def _e1_router_signals(panel: pd.DataFrame, tf: str, hold_bars: int) -> pd.DataFrame:
    """In BULL or trending_up: A2 EMA stack crossover LONG.
    In BEAR or trending_dn: A2 SHORT.
    In SIDEWAYS (markov=0) AND ranging (regime_label=ranging): B1 RSI mean-reversion.
    Use AND for sideways (true sideways), OR for trends (any trending signal).
    """
    ema_sig = _ema_stack_signal(panel)
    rsi_sig = _rsi_meanrev_signal(panel)
    mk = _markov_int(panel)
    rl = _regime_label(panel)

    # Trend defined as ANY (markov bull OR regime_label trending_up). Same for dn.
    trend_up = (mk == 1) | (rl == 1)
    trend_dn = (mk == -1) | (rl == -1)
    # Sideways = markov sideways AND not trending in label
    sideways = (mk == 0) & (rl == 0)

    fire = np.zeros(len(panel), dtype=np.int8)
    fire[trend_up & (ema_sig == 1)] = 1
    fire[trend_dn & (ema_sig == -1)] = -1
    fire[sideways & (rsi_sig != 0)] = rsi_sig[sideways & (rsi_sig != 0)]

    # Tag each fire with its regime: +1=trend_up, -1=trend_dn, 0=sideways
    reg_arr = np.where(trend_up, 1, np.where(trend_dn, -1, 0)).astype(np.int8)
    return _build_fires(panel, tf, fire, hold_bars, regime_arr=reg_arr)


def _e1_components(panel: pd.DataFrame, tf: str, hold_bars: int) -> dict[str, pd.DataFrame]:
    """Return component fires separately (for additive-lift comparison)."""
    ema_sig = _ema_stack_signal(panel)
    rsi_sig = _rsi_meanrev_signal(panel)
    return {
        "A2_only": _build_fires(panel, tf, ema_sig, hold_bars, regime_arr=_combo_regime(_markov_int(panel), _regime_label(panel))),
        "B1_only": _build_fires(panel, tf, rsi_sig, hold_bars, regime_arr=_combo_regime(_markov_int(panel), _regime_label(panel))),
    }


def _combo_regime(mk: np.ndarray, rl: np.ndarray) -> np.ndarray:
    """Combine markov + regime_label into a single tag: +1, 0, -1."""
    out = np.zeros_like(mk, dtype=np.int8)
    out[(mk == 1) | (rl == 1)] = 1
    out[(mk == -1) | (rl == -1)] = -1
    return out


def _build_fires(panel: pd.DataFrame, tf: str, fire_arr: np.ndarray,
                 hold_bars: int, regime_arr: np.ndarray | None = None,
                 lev_arr: np.ndarray | None = None,
                 size_arr: np.ndarray | None = None) -> pd.DataFrame:
    """Build a signals DataFrame from a per-bar +1/-1/0 fire array. Filters
    overlap by skipping fires while currently in position."""
    idx = np.where(fire_arr != 0)[0]
    if len(idx) == 0:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us", "fire_dir",
                                     "regime", "leverage", "notional_usd"])
    bar_us = _bar_us(tf)
    open_time_us = panel["ts_us"].to_numpy(dtype=np.int64)
    sig_us = open_time_us[idx] + bar_us
    dir_arr = fire_arr[idx]
    exit_us = sig_us + hold_bars * bar_us
    direction = np.where(dir_arr == 1, "LONG", "SHORT")
    regime = regime_arr[idx] if regime_arr is not None else np.zeros(len(idx), dtype=np.int8)
    leverage = lev_arr[idx] if lev_arr is not None else np.ones(len(idx), dtype=float)
    notional = size_arr[idx] if size_arr is not None else np.full(len(idx), 250.0)

    # Filter overlap: drop a fire if its signal_us falls before the prior fire's exit_us.
    keep = []
    last_exit = -np.inf
    for i in range(len(idx)):
        if sig_us[i] >= last_exit:
            keep.append(i)
            last_exit = exit_us[i]
    return pd.DataFrame({
        "signal_us": sig_us[keep],
        "direction": direction[keep],
        "exit_us": exit_us[keep],
        "fire_dir": dir_arr[keep],
        "regime": regime[keep],
        "leverage": leverage[keep],
        "notional_usd": notional[keep],
    })


# --------------------------------------------------------------------------- #
# E2 — Vol-regime leverage sizing on A3                                        #
# --------------------------------------------------------------------------- #

def _e2_signals(panel: pd.DataFrame, tf: str, hold_bars: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (vol_sized, flat_1x) signal frames."""
    adx_sig = _adx_trend_signal(panel, adx_thresh=20.0)
    vol = _vol_buckets(panel, lookback=60)
    # leverage: low→2.0, mid→1.0, high→0.5
    lev = np.where(vol == 0, 2.0, np.where(vol == 1, 1.0, 0.5))
    flat = np.ones_like(lev)
    return (
        _build_fires(panel, tf, adx_sig, hold_bars, regime_arr=vol, lev_arr=lev),
        _build_fires(panel, tf, adx_sig, hold_bars, regime_arr=vol, lev_arr=flat),
    )


# --------------------------------------------------------------------------- #
# E3 — Session-conditional strategy switch                                     #
# --------------------------------------------------------------------------- #

def _e3_signals(panel: pd.DataFrame, tf: str, hold_bars: int) -> dict[str, pd.DataFrame]:
    """Sessions: London+NY → Donchian breakout, Asia → RSI mean-rev."""
    donch = _donchian_breakout_signal(panel, lookback=20)
    rsi_mr = _rsi_meanrev_signal(panel)
    sess = _session_int(panel)
    composite = np.zeros(len(panel), dtype=np.int8)
    # London=1 or NY=2 → donchian; Asia=0 → RSI MR
    not_asia = sess != 0
    is_asia = sess == 0
    composite[not_asia & (donch != 0)] = donch[not_asia & (donch != 0)]
    composite[is_asia & (rsi_mr != 0)] = rsi_mr[is_asia & (rsi_mr != 0)]
    return {
        "composite": _build_fires(panel, tf, composite, hold_bars, regime_arr=sess),
        "A1_only": _build_fires(panel, tf, donch, hold_bars, regime_arr=sess),
        "B1_only": _build_fires(panel, tf, rsi_mr, hold_bars, regime_arr=sess),
    }


# --------------------------------------------------------------------------- #
# E4 — Cyclops as confidence multiplier on A2                                  #
# --------------------------------------------------------------------------- #

def _e4_signals(panel: pd.DataFrame, tf: str, hold_bars: int) -> dict[str, pd.DataFrame]:
    """A2 base (EMA stack crossover); notional scaled by # Cyclops axes aligned.
    Use trend + momentum axes (levels axis is sparse, only ~10% non-zero,
    rendering 3-of-3 nearly impossible — drop it). Axes ∈ {trend, momentum}.
    """
    ema_sig = _ema_stack_signal(panel)
    trend_v, levels_v, momentum_v = _cyclops_axes(panel)
    align = np.zeros(len(panel), dtype=np.int8)
    long_mask = ema_sig == 1
    short_mask = ema_sig == -1
    if long_mask.any():
        align[long_mask] = ((trend_v[long_mask] == 1).astype(int) +
                            (levels_v[long_mask] == 1).astype(int) +
                            (momentum_v[long_mask] == 1).astype(int))
    if short_mask.any():
        align[short_mask] = ((trend_v[short_mask] == -1).astype(int) +
                             (levels_v[short_mask] == -1).astype(int) +
                             (momentum_v[short_mask] == -1).astype(int))
    # Confidence multiplier: 3 axes → $500, 2 → $250, <2 → skip.
    # The original perp-native intent: "All 3 axes aligned → 2x, 2 axes → 1x, less → skip."
    size = np.where(align == 3, 500.0,
                    np.where(align == 2, 250.0, 0.0))
    fire = np.where(size > 0, ema_sig, 0).astype(np.int8)
    return {
        "composite": _build_fires(panel, tf, fire, hold_bars, regime_arr=align, size_arr=size),
        "A2_only": _build_fires(panel, tf, ema_sig, hold_bars, regime_arr=align,
                                size_arr=np.full(len(panel), 250.0)),
    }


# --------------------------------------------------------------------------- #
# Backtest helper — splits by leverage / notional, calls run_backtest          #
# --------------------------------------------------------------------------- #

def _backtest_fires(panel: pd.DataFrame, funding: pd.DataFrame, asset: str,
                    fires: pd.DataFrame, cfg: HyperliquidConfig) -> pd.DataFrame:
    """Run backtest splitting by (leverage, notional). Returns concatenated trades."""
    if len(fires) == 0:
        return pd.DataFrame(columns=["asset", "direction", "signal_us", "entry_us",
                                     "entry_price", "exit_us", "exit_price",
                                     "notional_usd", "leverage", "fee_in_usd",
                                     "fee_out_usd", "slippage_usd", "funding_paid_usd",
                                     "pnl_gross_usd", "pnl_net_usd", "bars_held",
                                     "exit_reason", "regime"])
    klines = panel[["ts_us", "open", "high", "low", "close"]].rename(
        columns={"ts_us": "open_time_us"})
    all_trades = []
    for (lev, notional), sub in fires.groupby(["leverage", "notional_usd"]):
        sig_sub = sub[["signal_us", "direction", "exit_us"]].copy()
        tdf, _ = run_backtest(klines, funding, sig_sub, asset,
                              notional_usd=float(notional), leverage=float(lev), cfg=cfg)
        if len(tdf) > 0:
            # Carry regime label per trade
            tdf = tdf.reset_index(drop=True)
            sub_re = sub.reset_index(drop=True)
            tdf["regime"] = sub_re["regime"].to_numpy()[:len(tdf)]
            all_trades.append(tdf)
    if not all_trades:
        return pd.DataFrame()
    return pd.concat(all_trades, ignore_index=True).sort_values("entry_us").reset_index(drop=True)


def _stats(trades: pd.DataFrame, tf: str) -> dict:
    if len(trades) == 0:
        return {"n_trades": 0, "win_rate": float("nan"), "total_pnl_usd": 0.0,
                "avg_pnl_usd": float("nan"), "sharpe_ann": float("nan"),
                "max_dd_usd": 0.0, "calmar": float("nan"), "avg_bars_held": float("nan"),
                "avg_funding": 0.0, "avg_fees": 0.0, "profit_factor": float("nan")}
    pnl = trades["pnl_net_usd"].to_numpy()
    wins = int((pnl > 0).sum())
    losses = int((pnl < 0).sum())
    bars_held = float(trades["bars_held"].mean())
    # Sharpe annualised: bar-period scaling
    bars_per_year = _bars_per_year(tf)
    avg_hold = max(1.0, bars_held)
    sharpe_ann = float("nan")
    if pnl.std() > 0:
        sharpe_ann = float((pnl.mean() / pnl.std()) * np.sqrt(bars_per_year / avg_hold))
    cum = np.cumsum(pnl)
    peaks = np.maximum.accumulate(cum)
    max_dd = float((cum - peaks).min()) if len(cum) else 0.0
    pf = float(pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum())) if losses > 0 else float("inf")
    calmar = float(pnl.sum() / abs(max_dd)) if max_dd != 0 else float("inf")
    return {
        "n_trades": int(len(trades)),
        "win_rate": float(wins) / len(trades),
        "total_pnl_usd": float(pnl.sum()),
        "avg_pnl_usd": float(pnl.mean()),
        "sharpe_ann": sharpe_ann,
        "max_dd_usd": max_dd,
        "calmar": calmar,
        "avg_bars_held": bars_held,
        "avg_funding": float(trades["funding_paid_usd"].mean()),
        "avg_fees": float((trades["fee_in_usd"] + trades["fee_out_usd"]).mean()),
        "profit_factor": pf,
    }


# --------------------------------------------------------------------------- #
# G6 / G7 helpers                                                              #
# --------------------------------------------------------------------------- #

def _bootstrap_sharpe_ci(pnl: np.ndarray, tf: str, n_boot: int = 5000, seed: int = 42) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(pnl)
    if n < 30:
        return float("nan"), float("nan")
    bars_per_year = _bars_per_year(tf)
    # Use a representative hold of 1 bar for the annualization factor
    boots = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        sample = pnl[rng.integers(0, n, size=n)]
        if sample.std() > 0:
            boots[b] = sample.mean() / sample.std() * np.sqrt(bars_per_year)
        else:
            boots[b] = 0.0
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def _regime_holdout(trades: pd.DataFrame, tf: str, regime_labels: dict) -> list[dict]:
    rows = []
    for label_int, label_name in regime_labels.items():
        sub = trades[trades["regime"] == label_int]
        s = _stats(sub, tf)
        rows.append({"regime": label_name, **s})
    return rows


# --------------------------------------------------------------------------- #
# Main sweep                                                                   #
# --------------------------------------------------------------------------- #

def _drop_warmup(panel: pd.DataFrame) -> pd.DataFrame:
    """Drop bars without basic indicator history."""
    return panel.dropna(subset=["atr_14", "rsi_14", "ema_50", "adx_14"]).reset_index(drop=True)


def _restrict_to_funding(panel: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """Restrict panel to window where funding data exists (so PnL includes funding)."""
    f_lo_us = int(funding.index.min().value // 1_000)
    p = panel[panel["ts_us"] >= f_lo_us].reset_index(drop=True)
    return p


def main() -> None:
    rows: list[dict] = []
    # Reload funding once per asset
    funding_cache = {asset: pd.read_parquet(FUNDING_DIR / f"{asset}_funding.parquet")
                     for asset in ("BTC", "ETH", "SOL")}
    cfg = HyperliquidConfig()
    # Hold horizons per TF. Wider holds let trend-following recoup fees.
    # 1h: 24-bar hold (1 day); 4h: 12-bar hold (2 days).
    hold_map = {"1h": 24, "4h": 12}

    detail_for_md: dict[str, dict] = {}
    buy_hold: dict[str, dict] = {}

    for asset in ("BTC", "ETH", "SOL"):
        funding = funding_cache[asset]
        for tf in ("1h", "4h"):
            ppath = PANEL_DIR / f"hl_panel_{asset}_{tf}.parquet"
            if not ppath.exists():
                print(f"SKIP missing panel: {ppath.name}")
                continue
            panel = _drop_warmup(pd.read_parquet(ppath))
            panel = _restrict_to_funding(panel, funding)
            if len(panel) < 500:
                print(f"SKIP {asset} {tf}: only {len(panel)} bars after warmup/funding filter")
                continue
            hold_bars = hold_map[tf]
            # Buy-and-hold benchmark over this exact window.
            buy_hold[f"{asset}_{tf}"] = _buy_hold_stats(panel, funding, tf)

            # ----------------- E1 router -----------------
            e1_fires = _e1_router_signals(panel, tf, hold_bars)
            e1_trades = _backtest_fires(panel, funding, asset, e1_fires, cfg)
            e1_stats = _stats(e1_trades, tf)
            comp = _e1_components(panel, tf, hold_bars)
            e1_a2_trades = _backtest_fires(panel, funding, asset, comp["A2_only"], cfg)
            e1_b1_trades = _backtest_fires(panel, funding, asset, comp["B1_only"], cfg)
            e1_a2_stats = _stats(e1_a2_trades, tf)
            e1_b1_stats = _stats(e1_b1_trades, tf)
            rows.append({"strategy": "E1_router", "asset": asset, "tf": tf,
                         "variant": "composite", **e1_stats})
            rows.append({"strategy": "E1_router", "asset": asset, "tf": tf,
                         "variant": "A2_only",   **e1_a2_stats})
            rows.append({"strategy": "E1_router", "asset": asset, "tf": tf,
                         "variant": "B1_only",   **e1_b1_stats})

            # ----------------- E2 vol sizing -----------------
            e2_sized, e2_flat = _e2_signals(panel, tf, hold_bars)
            e2_sized_t = _backtest_fires(panel, funding, asset, e2_sized, cfg)
            e2_flat_t = _backtest_fires(panel, funding, asset, e2_flat, cfg)
            e2_sized_s = _stats(e2_sized_t, tf)
            e2_flat_s = _stats(e2_flat_t, tf)
            rows.append({"strategy": "E2_vol_sized", "asset": asset, "tf": tf,
                         "variant": "vol_sized", **e2_sized_s})
            rows.append({"strategy": "E2_vol_sized", "asset": asset, "tf": tf,
                         "variant": "flat_1x",   **e2_flat_s})

            # ----------------- E3 session router -----------------
            e3 = _e3_signals(panel, tf, hold_bars)
            e3_comp_t = _backtest_fires(panel, funding, asset, e3["composite"], cfg)
            e3_a1_t = _backtest_fires(panel, funding, asset, e3["A1_only"], cfg)
            e3_b1_t = _backtest_fires(panel, funding, asset, e3["B1_only"], cfg)
            rows.append({"strategy": "E3_session", "asset": asset, "tf": tf,
                         "variant": "composite", **_stats(e3_comp_t, tf)})
            rows.append({"strategy": "E3_session", "asset": asset, "tf": tf,
                         "variant": "A1_only",   **_stats(e3_a1_t, tf)})
            rows.append({"strategy": "E3_session", "asset": asset, "tf": tf,
                         "variant": "B1_only",   **_stats(e3_b1_t, tf)})

            # ----------------- E4 cyclops confidence -----------------
            e4 = _e4_signals(panel, tf, hold_bars)
            e4_comp_t = _backtest_fires(panel, funding, asset, e4["composite"], cfg)
            e4_a2_t = _backtest_fires(panel, funding, asset, e4["A2_only"], cfg)
            rows.append({"strategy": "E4_cyclops_conf", "asset": asset, "tf": tf,
                         "variant": "composite", **_stats(e4_comp_t, tf)})
            rows.append({"strategy": "E4_cyclops_conf", "asset": asset, "tf": tf,
                         "variant": "A2_only",   **_stats(e4_a2_t, tf)})

            # Cache trade frames of the composite variants for G6/G7 deep-dive
            detail_for_md[f"E1_router__{asset}_{tf}"] = {
                "trades": e1_trades, "stats": e1_stats,
                "regime_labels": {1: "trend_up", 0: "sideways", -1: "trend_dn"},
            }
            detail_for_md[f"E2_vol_sized__{asset}_{tf}"] = {
                "trades": e2_sized_t, "stats": e2_sized_s,
                "regime_labels": {0: "low_vol", 1: "mid_vol", 2: "high_vol"},
            }
            detail_for_md[f"E3_session__{asset}_{tf}"] = {
                "trades": e3_comp_t, "stats": _stats(e3_comp_t, tf),
                "regime_labels": {0: "asia", 1: "london", 2: "ny"},
            }
            detail_for_md[f"E4_cyclops_conf__{asset}_{tf}"] = {
                "trades": e4_comp_t, "stats": _stats(e4_comp_t, tf),
                "regime_labels": {1: "1_axis", 2: "2_axes", 3: "3_axes"},
            }

            # Print a one-line summary
            print(f"{asset} {tf} E1 comp n={e1_stats['n_trades']:>4d} "
                  f"sharpe={e1_stats['sharpe_ann']:>5.2f} "
                  f"pnl=${e1_stats['total_pnl_usd']:>+8.0f} dd=${e1_stats['max_dd_usd']:>+8.0f} "
                  f"calmar={e1_stats['calmar']:>5.2f}")
            print(f"{asset} {tf} E2 sized n={e2_sized_s['n_trades']:>4d} "
                  f"sharpe={e2_sized_s['sharpe_ann']:>5.2f} "
                  f"pnl=${e2_sized_s['total_pnl_usd']:>+8.0f}  flat sharpe={e2_flat_s['sharpe_ann']:>5.2f}")
            print(f"{asset} {tf} E3 comp n={_stats(e3_comp_t, tf)['n_trades']:>4d} "
                  f"sharpe={_stats(e3_comp_t, tf)['sharpe_ann']:>5.2f} "
                  f"pnl=${_stats(e3_comp_t, tf)['total_pnl_usd']:>+8.0f}")
            print(f"{asset} {tf} E4 comp n={_stats(e4_comp_t, tf)['n_trades']:>4d} "
                  f"sharpe={_stats(e4_comp_t, tf)['sharpe_ann']:>5.2f} "
                  f"pnl=${_stats(e4_comp_t, tf)['total_pnl_usd']:>+8.0f}")

    results = pd.DataFrame(rows)
    results = results[["strategy", "asset", "tf", "variant", "n_trades", "win_rate",
                       "total_pnl_usd", "avg_pnl_usd", "sharpe_ann", "max_dd_usd",
                       "calmar", "profit_factor", "avg_bars_held", "avg_funding",
                       "avg_fees"]]
    out_csv = OUT_DIR / "E_results.csv"
    results.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv} ({len(results)} rows)")

    # ---------------- Build report ----------------
    _write_report(results, detail_for_md, buy_hold)


def _buy_hold_stats(panel: pd.DataFrame, funding: pd.DataFrame, tf: str,
                    notional_usd: float = 250.0) -> dict:
    """Compute buy-and-hold over the same window — single LONG at first bar,
    exit at last bar. Includes fees + funding."""
    if len(panel) < 2:
        return {"sharpe_ann": float("nan"), "total_pnl_usd": 0.0,
                "max_dd_usd": 0.0, "calmar": float("nan")}
    cfg = HyperliquidConfig()
    bar_us = _bar_us(tf)
    first = panel.iloc[0]
    last = panel.iloc[-1]
    p0 = float(first["open"])
    pN = float(last["close"])
    fee_in = notional_usd * (cfg.taker_fee_bps / 10_000.0)
    fee_out = notional_usd * (cfg.taker_fee_bps / 10_000.0)
    slip = notional_usd * (cfg.slippage_bps / 10_000.0)
    # Funding over the entire holding interval
    cap_frac = float(cfg.funding_cap_bps_hr) / 10_000.0
    f = funding[(funding.index.view("int64") // 1_000 >= int(first["ts_us"])) &
                (funding.index.view("int64") // 1_000 < int(last["ts_us"]))]
    rates = f["fundingRate"].clip(lower=-cap_frac, upper=+cap_frac).to_numpy()
    funding_paid = notional_usd * rates.sum()  # long pays positive rate
    pnl_gross = notional_usd * (pN / p0 - 1.0)
    pnl_net = pnl_gross - fee_in - fee_out - slip - funding_paid
    # Approximate "max DD" using daily close path
    closes = panel["close"].to_numpy()
    eq = (closes / p0) * notional_usd - notional_usd
    peaks = np.maximum.accumulate(eq)
    dd = (eq - peaks).min()
    bars = len(panel)
    avg_hold = bars  # single trade spans full window
    # Annualize: a single sample can't compute sharpe; use mean daily return
    daily = np.diff(np.log(closes))
    sharpe_ann = float("nan")
    if len(daily) > 1 and daily.std() > 0:
        sharpe_ann = float((daily.mean() / daily.std()) * np.sqrt(_bars_per_year(tf)))
    calmar = float(pnl_net / abs(dd)) if dd != 0 else float("inf")
    return {"sharpe_ann": sharpe_ann, "total_pnl_usd": float(pnl_net),
            "max_dd_usd": float(dd), "calmar": calmar, "bars": int(bars)}


def _write_report(results: pd.DataFrame, detail: dict[str, dict],
                  buy_hold: dict | None = None) -> None:
    """Markdown report: top 5 composites + per-strategy additive lift table."""
    md = []
    md.append("# E - Regime composite (perp-native rebuild)")
    md.append("")
    md.append("**Output**: `strategy_lab/hl_research_2026_05_26/wave2_perp/E_results.csv`")
    md.append("")
    md.append("## Hypothesis")
    md.append("Regime is a **strategy router** and **sizing multiplier**, not a binary gate. ")
    md.append("E1 routes to A2 trend or B1 mean-rev based on Markov+regime_label. ")
    md.append("E2 applies vol-bucket leverage on A3. E3 switches A1/B1 by session. ")
    md.append("E4 uses Cyclops 3-axis count as confidence multiplier on A2 notional.")
    md.append("")
    md.append("## Top 5 composite cells (sharpe_ann + calmar rank-sum)")
    comps = results[results["variant"].isin(["composite", "vol_sized"])].copy()
    comps = comps[comps["n_trades"] >= 30].copy()
    if len(comps):
        comps["rank"] = comps["sharpe_ann"].rank(ascending=False) + comps["calmar"].rank(ascending=False)
        top = comps.sort_values("rank").head(5)
        md.append("| Strategy | Asset | TF | n | win_rate | total_pnl | sharpe | calmar | max_dd |")
        md.append("|---|---|---|---|---|---|---|---|---|")
        for _, r in top.iterrows():
            md.append(f"| {r['strategy']} | {r['asset']} | {r['tf']} | {int(r['n_trades'])} | "
                     f"{r['win_rate']:.3f} | ${r['total_pnl_usd']:+.0f} | "
                     f"{r['sharpe_ann']:.2f} | {r['calmar']:.2f} | ${r['max_dd_usd']:+.0f} |")
    md.append("")

    # Composite vs component (additive lift)
    md.append("## Lift summary — composite Sharpe minus best component Sharpe")
    md.append("")
    md.append("| Strategy | Asset | TF | composite | best_comp | lift | verdict |")
    md.append("|---|---|---|---|---|---|---|")
    for strat in ("E1_router", "E2_vol_sized", "E3_session", "E4_cyclops_conf"):
        sub = results[results["strategy"] == strat]
        comp_var = "vol_sized" if strat == "E2_vol_sized" else "composite"
        for (asset, tf), grp in sub.groupby(["asset", "tf"]):
            comp_row = grp[grp["variant"] == comp_var]
            comps = grp[grp["variant"] != comp_var]
            if comp_row.empty or comps.empty:
                continue
            cs = comp_row["sharpe_ann"].iloc[0]
            bcs = comps["sharpe_ann"].max()
            lift = cs - bcs
            verdict = ("LIFT" if lift > 0.1 else ("FLAT" if lift > -0.1 else "DRAG"))
            md.append(f"| {strat} | {asset} | {tf} | {cs:+.2f} | {bcs:+.2f} | "
                     f"{lift:+.2f} | {verdict} |")
    md.append("")
    md.append("## Additive lift: composite vs each component standalone (full)")
    md.append("")
    for strat in ("E1_router", "E2_vol_sized", "E3_session", "E4_cyclops_conf"):
        sub = results[results["strategy"] == strat]
        if sub.empty:
            continue
        md.append(f"### {strat}")
        md.append("| Asset | TF | Variant | n | Sharpe | PnL | Calmar |")
        md.append("|---|---|---|---|---|---|---|")
        for _, r in sub.iterrows():
            md.append(f"| {r['asset']} | {r['tf']} | {r['variant']} | "
                     f"{int(r['n_trades'])} | {r['sharpe_ann']:.2f} | "
                     f"${r['total_pnl_usd']:+.0f} | {r['calmar']:.2f} |")
        md.append("")

    # G6 bootstrap + G7 regime hold-out for top composite cells
    md.append("## G6 / G7 deep-dive - composite cells with n >= 50")
    md.append("")
    for key, det in detail.items():
        trades = det["trades"]
        if len(trades) < 50:
            continue
        strat, ass_tf = key.split("__")
        asset, tf = ass_tf.split("_")
        lo, hi = _bootstrap_sharpe_ci(trades["pnl_net_usd"].to_numpy(), tf, n_boot=5000)
        g7_rows = _regime_holdout(trades, tf, det["regime_labels"])
        md.append(f"### {strat} - {asset} {tf}")
        md.append(f"- n_trades={len(trades)}  total_pnl=${trades['pnl_net_usd'].sum():+.0f}  "
                  f"sharpe={det['stats']['sharpe_ann']:.2f}")
        md.append(f"- **G6 Sharpe 95% CI**: [{lo:.2f}, {hi:.2f}]  "
                  f"({'PASS' if (np.isfinite(lo) and lo > 0) else 'FAIL'})")
        md.append("")
        md.append("**G7 per-regime hold-out**")
        md.append("| Regime | n | Sharpe | PnL | WR |")
        md.append("|---|---|---|---|---|")
        for r in g7_rows:
            md.append(f"| {r['regime']} | {r['n_trades']} | {r['sharpe_ann']:.2f} | "
                     f"${r['total_pnl_usd']:+.0f} | {r['win_rate']:.3f} |")
        md.append("")

    if buy_hold:
        md.append("## Buy-and-hold benchmark (single LONG over full window, $250 notional)")
        md.append("| Asset | TF | total_pnl | sharpe | calmar | max_dd | bars |")
        md.append("|---|---|---|---|---|---|---|")
        for k, bh in buy_hold.items():
            asset, tf = k.split("_")
            md.append(f"| {asset} | {tf} | ${bh['total_pnl_usd']:+.0f} | "
                     f"{bh['sharpe_ann']:.2f} | {bh['calmar']:.2f} | "
                     f"${bh['max_dd_usd']:+.0f} | {bh['bars']} |")
        md.append("")

    md.append("## Notes")
    md.append("- All trades use HL taker 4.5 bps each side + 3 bps slippage + hourly funding accrual.")
    md.append("- E2 leverage range: low_vol=2.0x / mid_vol=1.0x / high_vol=0.5x. E4 notional: 2_of_3 -> $250, 3_of_3 -> $500.")
    md.append("- Overlap-aware: a new fire is skipped while still in a position.")
    md.append("- Sharpe annualization uses bar-period scaling (bars_per_year / avg_bars_held).")
    md.append("- Composite vs component comparison enables additive-lift verification (G_lift).")
    md.append("- Window: ~2023-05 to ~2026-03 (~34 months) where HL funding overlaps with Binance klines.")
    md.append("")

    md_path = OUT_DIR / "E_regime_composite.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
