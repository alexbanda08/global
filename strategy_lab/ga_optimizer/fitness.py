"""
Fitness function for GA. Wraps the lookahead-corrected backtest harness.

PnL-heavy / WR composite (per user lock):
  fitness = 0.6 * normalized_pnl + 0.3 * win_rate_lift + 0.1 * n_gate

where:
  normalized_pnl  = sign(pnl) * log1p(|pnl|) / log1p(1000)   (scale-stable in $)
  win_rate_lift   = (win_rate - 0.5) * 2                     (range [-1, +1])
  n_gate          = min(1.0, n_trades / 100)                 (penalize <100 trades)

Penalties:
  - if n_trades < 30: fitness = -1e9 (discard)
  - if max single-day DD > 50% of total PnL: penalize by half (volatile)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import datetime as _dt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming, asof_strict
from harness import SPREAD_FILTER, NOTIONAL, FEE_RATE, walk_asks, get_book_at

# Critical: shift all kline asof reads by this much to avoid microsec lookahead
LATENCY_US = 100_000


def hour_in_mask(mask: int, hour: int) -> bool:
    return bool((mask >> hour) & 1)


def dow_in_mask(mask: int, dow: int) -> bool:
    return bool((mask >> dow) & 1)


def _compute_sigma(end_us, prices, fire_us, lookback_min):
    idx = int(np.searchsorted(end_us, fire_us, side="right") - 1)
    if idx < lookback_min:
        return 0.0
    sl = prices[idx - lookback_min + 1 : idx + 1]
    if len(sl) < 5:
        return 0.0
    rets = np.diff(np.log(sl))
    rets = rets[np.isfinite(rets)]
    return float(np.std(rets)) if len(rets) >= 5 else 0.0


def _fair_p_up(ret, sigma, z_scale=2.0):
    if not np.isfinite(ret) or sigma <= 0:
        return 0.5
    z = ret / sigma
    p = 0.5 + 0.5 * np.tanh(z_scale * z)
    return float(np.clip(p, 0.10, 0.90))


def evaluate_momo(individual: dict, sleeve_type: str, asset: str,
                  res: pd.DataFrame, books: dict,
                  klines_end_us: np.ndarray, klines_prices: np.ndarray,
                  window_us: tuple[int, int] | None = None) -> pd.DataFrame:
    """
    Run momo sleeve with this individual's params on the universe restricted to
    (asset, window). Returns DataFrame of fired trades with PnL.
    """
    window_s = {"momo_5m": 300, "momo_15m": 900}[sleeve_type]
    tf = "5m" if sleeve_type == "momo_5m" else "15m"
    sub = res[(res.ticker == asset) & (res.timeframe == tf)].copy()
    if window_us is not None:
        sub = sub[(sub.slot_start_us >= window_us[0]) & (sub.slot_start_us < window_us[1])]
    if len(sub) == 0:
        return pd.DataFrame()

    # Time filter
    sub["ts"] = pd.to_datetime(sub.slot_start_us, unit="us", utc=True)
    hour_mask = individual["hour_mask"]
    dow_mask = individual["dow_mask"]
    sub = sub[sub.ts.dt.hour.apply(lambda h: hour_in_mask(hour_mask, h))]
    sub = sub[sub.ts.dt.dayofweek.apply(lambda d: dow_in_mask(dow_mask, d))]
    if len(sub) == 0:
        return pd.DataFrame()

    # Production momo fire timing: fire_us = ws_s + 120 = slot_start - window + 120
    sub["fire_us"] = sub.slot_start_us - window_s * 1_000_000 + 120 * 1_000_000

    SPREAD = SPREAD_FILTER[asset]
    NOT = float(individual["notional_usd"])
    thr_bp = float(individual["ret_2m_threshold_bp"])
    dir_mode = individual["direction_mode"]
    sigma_min = int(individual["sigma_window_min"])
    spread_max = float(individual["spread_max"])
    vwap_lo = float(individual["vwap_lo"])
    vwap_hi = float(individual["vwap_hi"])

    rows = []
    for _, r in sub.iterrows():
        fire_us = int(r.fire_us)
        fire_us_kline = fire_us - LATENCY_US   # lookahead-correction
        # ret_2m: binance return over [fire-120s, fire] (production momo definition)
        p_now = asof_strict(klines_end_us, klines_prices, fire_us_kline)
        p_then = asof_strict(klines_end_us, klines_prices, fire_us_kline - 120 * 1_000_000)
        if not (np.isfinite(p_now) and np.isfinite(p_then) and p_then > 0):
            continue
        ret_2m_bp = (p_now / p_then - 1.0) * 1e4    # in bp
        if abs(ret_2m_bp) < thr_bp:
            continue

        # Signal direction
        if dir_mode == "same":
            signal = "UP" if ret_2m_bp > 0 else "DOWN"
        else:  # fade
            signal = "DOWN" if ret_2m_bp > 0 else "UP"

        # Book lookup (safe_us = fire_us - latency_us — book usually safe at this margin)
        snap_self = get_book_at(books, r.slug, signal.title(), fire_us)
        if snap_self is None:
            continue
        ap, asz, bp, bsz = snap_self
        if not (np.isfinite(ap[0]) and np.isfinite(bp[0])):
            continue
        if (ap[0] - bp[0]) > spread_max:
            continue

        vwap, shares, spent, under = walk_asks(list(ap), list(asz), NOT)
        if under or not np.isfinite(vwap) or shares <= 0:
            continue
        if not (vwap_lo < vwap < vwap_hi):
            continue

        won = int(signal == r.outcome.upper())
        profit_raw = shares * (won - vwap)
        fee = max(profit_raw, 0.0) * FEE_RATE
        pnl = profit_raw - fee
        rows.append(dict(
            slug=r.slug, fire_us=fire_us, signal=signal,
            outcome=r.outcome, ret_2m_bp=ret_2m_bp, vwap=vwap,
            shares=shares, won=won, pnl=pnl,
        ))
    return pd.DataFrame(rows)


def fitness(trades: pd.DataFrame, individual: dict | None = None) -> dict:
    """
    Compute fitness from a trades DataFrame.
    Returns dict with:
      fitness   (composite scalar — higher is better)
      pnl       total PnL
      n         trade count
      win_rate
      sharpe    annualized daily Sharpe
      max_dd    max daily-cumulative drawdown
      details   for debug
    """
    n = len(trades)
    if n < 30:
        return dict(fitness=-1e9, pnl=0.0, n=n, win_rate=0.0,
                     sharpe=0.0, max_dd=0.0, details="n<30")

    pnl = float(trades.pnl.sum())
    win_rate = float(trades.won.mean())

    # Daily series for Sharpe + DD
    trades = trades.copy()
    trades["date"] = pd.to_datetime(trades.fire_us, unit="us", utc=True).dt.date
    daily = trades.groupby("date").pnl.sum()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    cs = daily.cumsum()
    peak = cs.expanding().max()
    dd = (cs - peak).min() if len(cs) else 0.0

    # PnL-heavy / WR composite (per user lock)
    norm_pnl = np.sign(pnl) * np.log1p(abs(pnl)) / np.log1p(1000)
    wr_lift = (win_rate - 0.5) * 2
    n_gate = min(1.0, n / 100.0)
    raw_fit = 0.6 * norm_pnl + 0.3 * wr_lift + 0.1 * n_gate

    # Penalize high DD relative to total PnL
    dd_penalty = 0.0
    if pnl > 0 and abs(dd) > 0.5 * pnl:
        dd_penalty = 0.3 * (abs(dd) / max(pnl, 1.0) - 0.5)
    raw_fit -= dd_penalty

    return dict(
        fitness=float(raw_fit), pnl=pnl, n=n, win_rate=win_rate,
        sharpe=sharpe, max_dd=float(dd), norm_pnl=norm_pnl, wr_lift=wr_lift,
        n_gate=n_gate, dd_penalty=dd_penalty,
    )
