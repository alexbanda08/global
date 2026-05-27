"""
hl_engine.py — Hyperliquid perpetual futures backtest engine.

Adapter that ports `strategy_lab/engine_v2.py` (Polymarket binary $25 stake,
2%-on-profit-or-curve fee) to Hyperliquid perps where positions are sized,
leverage is variable, fees are bps-of-notional per side, and funding accrues
hourly on the open position.

Differences vs Polymarket engine_v2.py:
  - No 0/1 settlement; close-out at exit kline open/close/VWAP.
  - Fees: HL taker 4.5 bps + maker 1.5 bps, applied as `notional × bps/10000`
    on EACH side (entry AND exit) — NOT the "2% on profit" Poly shortcut.
  - Funding: hourly accrual. For LONG, funding_rate>0 → trader PAYS; SHORT
    receives. Total funding = Σ (notional × leverage × rate_h) over hours held.
  - Latency: bar-aligned, not microsecond book-walk. The signal at `signal_us`
    fills at the open of the FIRST kline whose open_time ≥ signal_us + latency.
  - Slippage: bps of entry notional, modeled as upfront cost (matches V52
    backtest's `slip = 0.0003` convention).

API
---

>>> from strategy_lab.hl_research_2026_05_26.hl_engine import (
...     HyperliquidConfig, fill_at_kline, simulate_with_funding, run_backtest,
... )
>>> cfg = HyperliquidConfig()
>>> fill = fill_at_kline(klines, "BTC", signal_us, "LONG", notional_usd=250)
>>> trade = simulate_with_funding(klines, funding, fill, exit_us, cfg=cfg)
>>> trades_df, stats = run_backtest(klines, funding, signals, "BTC", cfg=cfg)

Constants (V52-validated for HL majors):
  taker_fee_bps  = 4.5     (0.045%)
  maker_fee_bps  = 1.5     (0.015%)
  slippage_bps   = 3.0     (3 bps round-trip headwind, matches V52's slip=0.0003)
  latency_ms     = 50      (Frankfurt → HL Arbitrum sequencer; lower than Poly 85ms)
  funding_cap    = 1.25 bps/hr per HL docs (saturates at extreme premiums)

Conventions
-----------
- All timestamps are UTC microseconds (`*_us`) matching the project convention.
- `klines` DataFrame must have either an `open_time_us` (int64) column OR a
  tz-aware datetime column named `open_time` (we normalize internally).
- `funding` DataFrame must be indexed by tz-aware UTC `timestamp` OR have a
  `funding_time_us` int64 column.
- Funding sign convention (HL spec): `fundingRate > 0` → longs pay shorts. So
  funding cost for a long = +notional × leverage × rate (positive = cost).
  For a short = -notional × leverage × rate (negative cost = income).

Smoke test
----------
Run `python -m strategy_lab.hl_research_2026_05_26.hl_engine` to load BTC 1h
klines + funding parquet, generate 100 random LONG signals, run a backtest
at (lev=1, hold=1h) and (lev=3, hold=24h), and print summary stats.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HyperliquidConfig:
    """Live-mimic config for Hyperliquid perpetuals."""
    taker_fee_bps: float = 4.5            # HL taker = 0.045%
    maker_fee_bps: float = 1.5            # HL maker = 0.015%
    funding_method: Literal["hourly_accrual", "settled_8h", "ignore"] = "hourly_accrual"
    latency_ms: float = 50.0              # Frankfurt → HL Arbitrum sequencer
    slippage_bps: float = 3.0             # bps of notional, modeled as upfront cost
    fill_model: Literal[
        "kline_next_open", "kline_next_close", "vwap", "book_walk"
    ] = "kline_next_open"
    max_leverage: float = 5.0
    funding_cap_bps_hr: float = 1.25      # HL docs: 1.25 bps/hr cap


@dataclass(frozen=True)
class HyperliquidLegacyConfig(HyperliquidConfig):
    """Reproduce V52's exact fee/funding model for cross-validation.

    V52 spec from `docs/deployment/V52_HYPERLIQUID_DEPLOYMENT_NOTES.md`:
      - taker 4.5 bps, slip 3 bps on entry only, funding hourly accrual.
      - No partial-fill modeling; fill at next-bar open.
    """
    taker_fee_bps: float = 4.5
    maker_fee_bps: float = 1.5
    funding_method: Literal["hourly_accrual", "settled_8h", "ignore"] = "hourly_accrual"
    latency_ms: float = 0.0               # V52 has no explicit latency model
    slippage_bps: float = 3.0
    fill_model: Literal[
        "kline_next_open", "kline_next_close", "vwap", "book_walk"
    ] = "kline_next_open"
    max_leverage: float = 3.0
    funding_cap_bps_hr: float = 1.25


# ---------------------------------------------------------------------------
# Data classes for fills and trades
# ---------------------------------------------------------------------------

@dataclass
class HLFill:
    """One side of a Hyperliquid perpetual position."""
    asset: str
    direction: Literal["LONG", "SHORT"]
    entry_us: int
    entry_price: float
    notional_usd: float          # = position_size × entry_price
    leverage: float
    fee_paid_usd: float          # entry-side fee (taker bps × notional)
    slippage_usd: float          # entry-side slippage (bps × notional)
    fill_source: str             # "kline_next_open" / etc.


@dataclass
class HLTrade:
    """Full round-trip (entry + hold + exit) including funding accrual."""
    fill: HLFill
    exit_us: int
    exit_price: float
    exit_fee_paid_usd: float
    funding_paid_usd: float      # signed; +ve = trader paid
    pnl_gross_usd: float         # before any fees / funding / slippage
    pnl_net_usd: float           # gross - entry_fee - exit_fee - slippage - funding
    bars_held: int
    exit_reason: Literal[
        "signal_flip", "sl", "tp", "trailing", "time_stop", "end_of_data"
    ] = "time_stop"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_open_time_us(klines: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `klines` with an `open_time_us` int64 column added if
    missing. Accepts either `open_time` (tz-aware datetime) or `open_time_us`.
    Sorts ascending by `open_time_us`."""
    if "open_time_us" in klines.columns:
        out = klines
    elif "open_time" in klines.columns:
        out = klines.copy()
        ts = pd.to_datetime(out["open_time"], utc=True)
        out["open_time_us"] = (ts.astype("int64") // 1_000).astype("int64")
    elif isinstance(klines.index, pd.DatetimeIndex):
        out = klines.copy()
        idx = klines.index.tz_convert("UTC") if klines.index.tz is not None else klines.index.tz_localize("UTC")
        out["open_time_us"] = (idx.astype("int64") // 1_000).astype("int64")
    else:
        raise ValueError(
            "klines needs an `open_time_us` int64 col, an `open_time` datetime "
            "col, or a DatetimeIndex"
        )
    if not out["open_time_us"].is_monotonic_increasing:
        out = out.sort_values("open_time_us").reset_index(drop=True)
    return out


def _ensure_funding_us(funding: pd.DataFrame) -> pd.DataFrame:
    """Return funding df with `funding_time_us` int64 col and `funding_rate`
    float64 col. Handles tz-aware DatetimeIndex OR `funding_time_us`/`timestamp`
    columns. Coerces string-encoded rates to numeric."""
    out = funding.copy()
    # rate column
    if "funding_rate" in out.columns:
        rate_col = "funding_rate"
    elif "fundingRate" in out.columns:
        rate_col = "fundingRate"
        out = out.rename(columns={"fundingRate": "funding_rate"})
        rate_col = "funding_rate"
    else:
        raise ValueError("funding df missing `funding_rate` / `fundingRate` col")
    out["funding_rate"] = pd.to_numeric(out["funding_rate"], errors="coerce")
    # time column
    if "funding_time_us" not in out.columns:
        if isinstance(funding.index, pd.DatetimeIndex):
            idx = funding.index
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
            out["funding_time_us"] = (idx.astype("int64") // 1_000).astype("int64")
        elif "timestamp" in out.columns:
            ts = pd.to_datetime(out["timestamp"], utc=True)
            out["funding_time_us"] = (ts.astype("int64") // 1_000).astype("int64")
        else:
            raise ValueError(
                "funding df needs `funding_time_us` col OR a DatetimeIndex OR `timestamp` col"
            )
    out = out.dropna(subset=["funding_rate"])
    if not out["funding_time_us"].is_monotonic_increasing:
        out = out.sort_values("funding_time_us").reset_index(drop=True)
    return out


def _bar_period_us(klines: pd.DataFrame) -> int:
    """Estimate the kline period in microseconds from the median diff. Used
    for end-of-data fallback exits."""
    diffs = klines["open_time_us"].diff().dropna()
    if len(diffs) == 0:
        return 3_600_000_000   # 1h fallback
    return int(diffs.median())


# ---------------------------------------------------------------------------
# Fee + slippage primitives
# ---------------------------------------------------------------------------

def fee_usd(notional_usd: float, bps: float) -> float:
    """Convert a bps fee to a dollar cost on a notional. Always positive."""
    return abs(float(notional_usd)) * (float(bps) / 10_000.0)


def slippage_usd(notional_usd: float, bps: float) -> float:
    """Slippage in USD, modeled as bps of notional. Always positive (a cost)."""
    return abs(float(notional_usd)) * (float(bps) / 10_000.0)


# ---------------------------------------------------------------------------
# Funding accrual primitive
# ---------------------------------------------------------------------------

def funding_paid_between(
    funding: pd.DataFrame,
    entry_us: int,
    exit_us: int,
    notional_usd: float,
    leverage: float,
    direction: Literal["LONG", "SHORT"],
    cap_bps_hr: float = 1.25,
) -> float:
    """Total funding cost in USD for a position open over [entry_us, exit_us).

    For each hourly funding row whose timestamp falls in [entry_us, exit_us),
    we accrue `direction_sign × notional × leverage × min(rate, cap)`, where
    direction_sign = +1 for LONG (longs pay when rate > 0) and -1 for SHORT.

    Returns:
        Signed USD. POSITIVE = trader paid; NEGATIVE = trader received.
    """
    if "funding_time_us" not in funding.columns:
        funding = _ensure_funding_us(funding)
    if entry_us >= exit_us:
        return 0.0
    mask = (funding["funding_time_us"] >= int(entry_us)) & \
           (funding["funding_time_us"] < int(exit_us))
    sub = funding.loc[mask, "funding_rate"]
    if len(sub) == 0:
        return 0.0
    cap_frac = float(cap_bps_hr) / 10_000.0
    rates = sub.clip(lower=-cap_frac, upper=+cap_frac).to_numpy()
    sign = +1.0 if direction == "LONG" else -1.0
    pos_notional = abs(float(notional_usd)) * abs(float(leverage))
    return float(sign * pos_notional * rates.sum())


# ---------------------------------------------------------------------------
# Fill primitive
# ---------------------------------------------------------------------------

def fill_at_kline(
    klines: pd.DataFrame,
    asset: str,
    signal_us: int,
    direction: Literal["LONG", "SHORT"],
    notional_usd: float = 250.0,
    leverage: float = 1.0,
    cfg: HyperliquidConfig = HyperliquidConfig(),
) -> "HLFill | None":
    """Fill at the next bar's open after signal_us + latency.

    Returns None if no fill possible (e.g., signal at end of data, or
    leverage > cfg.max_leverage).
    """
    if leverage > cfg.max_leverage + 1e-9:
        return None
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"direction must be LONG/SHORT, got {direction!r}")

    kl = _ensure_open_time_us(klines)
    target_us = int(signal_us) + int(cfg.latency_ms * 1_000)
    times = kl["open_time_us"].to_numpy()
    # Find first bar with open_time_us > target_us (strictly after signal+latency)
    pos = int(np.searchsorted(times, target_us, side="right"))
    if pos >= len(kl):
        return None

    row = kl.iloc[pos]
    if cfg.fill_model == "kline_next_open":
        entry_price = float(row["open"])
        src = "kline_next_open"
    elif cfg.fill_model == "kline_next_close":
        entry_price = float(row["close"])
        src = "kline_next_close"
    elif cfg.fill_model == "vwap":
        # Simple VWAP proxy: (h+l+c)/3. Production should use trade-tape VWAP.
        entry_price = float((row["high"] + row["low"] + row["close"]) / 3.0)
        src = "vwap"
    elif cfg.fill_model == "book_walk":
        # Not implemented for HL klines; fall back to next-open with a note.
        entry_price = float(row["open"])
        src = "kline_next_open(book_walk_unimpl)"
    else:
        raise ValueError(f"unknown fill_model {cfg.fill_model!r}")

    notional_usd = abs(float(notional_usd))
    fee_in = fee_usd(notional_usd, cfg.taker_fee_bps)
    slip_in = slippage_usd(notional_usd, cfg.slippage_bps)

    return HLFill(
        asset=asset,
        direction=direction,
        entry_us=int(row["open_time_us"]),
        entry_price=entry_price,
        notional_usd=notional_usd,
        leverage=float(leverage),
        fee_paid_usd=fee_in,
        slippage_usd=slip_in,
        fill_source=src,
    )


# ---------------------------------------------------------------------------
# PnL primitives
# ---------------------------------------------------------------------------

def gross_pnl_usd(
    entry_price: float,
    exit_price: float,
    notional_usd: float,
    leverage: float,
    direction: Literal["LONG", "SHORT"],
) -> float:
    """Notional-and-leverage scaled PnL (no fees / funding / slippage)."""
    p_in = float(entry_price)
    p_out = float(exit_price)
    if p_in <= 0:
        return 0.0
    ret = (p_out / p_in) - 1.0
    sign = +1.0 if direction == "LONG" else -1.0
    return sign * float(notional_usd) * float(leverage) * ret


def close_at_kline(
    klines: pd.DataFrame,
    fill: HLFill,
    exit_us: int,
    cfg: HyperliquidConfig = HyperliquidConfig(),
) -> HLTrade:
    """Close at the kline whose open_time_us ≥ exit_us (next bar after exit
    signal). No funding accrual — use `simulate_with_funding` for that."""
    kl = _ensure_open_time_us(klines)
    target_us = int(exit_us) + int(cfg.latency_ms * 1_000)
    times = kl["open_time_us"].to_numpy()
    pos = int(np.searchsorted(times, target_us, side="right"))

    if pos >= len(kl):
        # End-of-data: exit at last available bar's close
        last = kl.iloc[-1]
        exit_price = float(last["close"])
        exit_actual_us = int(last["open_time_us"]) + _bar_period_us(kl)
        exit_reason: Literal[
            "signal_flip", "sl", "tp", "trailing", "time_stop", "end_of_data"
        ] = "end_of_data"
    else:
        row = kl.iloc[pos]
        if cfg.fill_model in ("kline_next_close",):
            exit_price = float(row["close"])
        elif cfg.fill_model == "vwap":
            exit_price = float((row["high"] + row["low"] + row["close"]) / 3.0)
        else:
            exit_price = float(row["open"])
        exit_actual_us = int(row["open_time_us"])
        exit_reason = "time_stop"

    pnl_gross = gross_pnl_usd(
        fill.entry_price, exit_price, fill.notional_usd,
        fill.leverage, fill.direction,
    )
    fee_out = fee_usd(fill.notional_usd * fill.leverage, cfg.taker_fee_bps)
    # No funding here — caller must use simulate_with_funding for that
    pnl_net = pnl_gross - fill.fee_paid_usd - fee_out - fill.slippage_usd

    # bars held
    entry_idx = int(np.searchsorted(times, fill.entry_us, side="left"))
    exit_idx = pos if pos < len(kl) else len(kl) - 1
    bars_held = max(0, exit_idx - entry_idx)

    return HLTrade(
        fill=fill,
        exit_us=exit_actual_us,
        exit_price=exit_price,
        exit_fee_paid_usd=fee_out,
        funding_paid_usd=0.0,
        pnl_gross_usd=pnl_gross,
        pnl_net_usd=pnl_net,
        bars_held=bars_held,
        exit_reason=exit_reason,
    )


def simulate_with_funding(
    klines: pd.DataFrame,
    funding: pd.DataFrame,
    fill: HLFill,
    exit_us: int,
    cfg: HyperliquidConfig = HyperliquidConfig(),
) -> HLTrade:
    """Full trade lifecycle: entry fee + hourly funding accrual + exit fee + slippage.

    Funding accrued over [fill.entry_us, exit_actual_us) inclusive of all
    hourly settlements that occurred in that interval.
    """
    # Close at kline first (no funding yet)
    trade_no_fund = close_at_kline(klines, fill, exit_us, cfg=cfg)

    # Funding over the realized holding interval
    if cfg.funding_method == "ignore":
        funding_paid = 0.0
    else:
        # We notional-scale funding by leverage too — HL settles on (size × price),
        # which already includes leverage when size = (notional × leverage) / price.
        funding_paid = funding_paid_between(
            funding,
            entry_us=fill.entry_us,
            exit_us=trade_no_fund.exit_us,
            notional_usd=fill.notional_usd,
            leverage=fill.leverage,
            direction=fill.direction,
            cap_bps_hr=cfg.funding_cap_bps_hr,
        )

    pnl_net = trade_no_fund.pnl_net_usd - funding_paid
    return HLTrade(
        fill=fill,
        exit_us=trade_no_fund.exit_us,
        exit_price=trade_no_fund.exit_price,
        exit_fee_paid_usd=trade_no_fund.exit_fee_paid_usd,
        funding_paid_usd=funding_paid,
        pnl_gross_usd=trade_no_fund.pnl_gross_usd,
        pnl_net_usd=pnl_net,
        bars_held=trade_no_fund.bars_held,
        exit_reason=trade_no_fund.exit_reason,
    )


# ---------------------------------------------------------------------------
# Vectorized backtest
# ---------------------------------------------------------------------------

def run_backtest(
    klines: pd.DataFrame,
    funding: pd.DataFrame,
    signals: pd.DataFrame,
    asset: str,
    notional_usd: float = 250.0,
    leverage: float = 1.0,
    cfg: HyperliquidConfig = HyperliquidConfig(),
) -> tuple[pd.DataFrame, dict]:
    """Vectorized backtest. One trade per signal row.

    `signals` columns:
      - signal_us  : int64 microsecond timestamp at which decision fires
      - direction  : "LONG" or "SHORT"
      - exit_us    : int64 microsecond exit-decision timestamp

    Returns:
        trades_df : DataFrame with one row per trade
        stats     : dict with n_trades, n_wins, win_rate, total_pnl_usd, etc.

    Vectorized: looks up entry and exit kline indices via two searchsorted
    calls, computes gross PnL with array ops, then accrues funding per-trade
    using `funding_paid_between` (which is itself a vectorized clip+sum).
    """
    if len(signals) == 0:
        return (
            pd.DataFrame(columns=[
                "asset", "direction", "signal_us", "entry_us", "entry_price",
                "exit_us", "exit_price", "notional_usd", "leverage",
                "fee_in_usd", "fee_out_usd", "slippage_usd",
                "funding_paid_usd", "pnl_gross_usd", "pnl_net_usd",
                "bars_held", "exit_reason",
            ]),
            {"n_trades": 0, "n_wins": 0, "win_rate": float("nan"),
             "total_pnl_usd": 0.0, "avg_pnl_usd": float("nan"),
             "sharpe": float("nan"), "max_dd_usd": 0.0,
             "avg_funding_paid": 0.0, "avg_fees_paid": 0.0,
             "avg_bars_held": float("nan"), "n_end_of_data": 0},
        )

    kl = _ensure_open_time_us(klines)
    fnd = _ensure_funding_us(funding)
    bar_us = _bar_period_us(kl)
    times = kl["open_time_us"].to_numpy()
    opens = kl["open"].to_numpy(dtype=float)
    closes = kl["close"].to_numpy(dtype=float)
    highs = kl["high"].to_numpy(dtype=float)
    lows = kl["low"].to_numpy(dtype=float)

    sig = signals.copy()
    sig["signal_us"] = sig["signal_us"].astype("int64")
    sig["exit_us"] = sig["exit_us"].astype("int64")
    sig["direction"] = sig["direction"].astype(str).str.upper()

    # Find entry kline index (first bar with open_time_us > signal_us + latency)
    entry_target = sig["signal_us"].to_numpy() + int(cfg.latency_ms * 1_000)
    entry_idx = np.searchsorted(times, entry_target, side="right")
    # Find exit kline index (first bar with open_time_us > exit_us + latency)
    exit_target = sig["exit_us"].to_numpy() + int(cfg.latency_ms * 1_000)
    exit_idx = np.searchsorted(times, exit_target, side="right")

    n = len(sig)
    n_bars = len(kl)

    # Validity mask: entry kline exists AND exit_idx > entry_idx
    valid = (entry_idx < n_bars) & (exit_idx > entry_idx)

    # Resolve fill prices per fill_model
    def _price_at(idx_arr: np.ndarray, eod_use_close: bool = False) -> np.ndarray:
        """Vectorized price lookup; clips end-of-data indices to last bar."""
        capped = np.clip(idx_arr, 0, n_bars - 1)
        if cfg.fill_model == "kline_next_open":
            px = opens[capped]
        elif cfg.fill_model == "kline_next_close":
            px = closes[capped]
        elif cfg.fill_model == "vwap":
            px = (highs[capped] + lows[capped] + closes[capped]) / 3.0
        else:
            px = opens[capped]
        if eod_use_close:
            eod_mask = idx_arr >= n_bars
            px = np.where(eod_mask, closes[n_bars - 1], px)
        return px

    entry_price = _price_at(entry_idx)
    exit_price = _price_at(exit_idx, eod_use_close=True)

    # Resolved entry / exit times
    entry_us_arr = np.where(
        entry_idx < n_bars, times[np.clip(entry_idx, 0, n_bars - 1)], -1
    )
    exit_us_arr = np.where(
        exit_idx < n_bars,
        times[np.clip(exit_idx, 0, n_bars - 1)],
        times[n_bars - 1] + bar_us,
    )

    # bars held
    bars_held = (np.clip(exit_idx, 0, n_bars - 1) - entry_idx).clip(min=0)

    # Direction sign
    dir_sign = np.where(sig["direction"].to_numpy() == "LONG", +1.0, -1.0)

    # PnL gross — vectorized
    ret = np.where(entry_price > 0, exit_price / entry_price - 1.0, 0.0)
    notional_arr = np.full(n, float(notional_usd))
    lev_arr = np.full(n, float(leverage))
    pos_notional = notional_arr * lev_arr
    pnl_gross = dir_sign * pos_notional * ret

    # Fees (taker, both sides) + slippage on entry side
    fee_in = pos_notional * (cfg.taker_fee_bps / 10_000.0)
    fee_out = pos_notional * (cfg.taker_fee_bps / 10_000.0)
    slip = pos_notional * (cfg.slippage_bps / 10_000.0)

    # Funding — per-trade, vectorized clip+sum over the funding rate array
    if cfg.funding_method == "ignore":
        funding_paid = np.zeros(n, dtype=float)
    else:
        funding_paid = _vectorized_funding(
            fnd, entry_us_arr, exit_us_arr, pos_notional, dir_sign,
            cap_bps_hr=cfg.funding_cap_bps_hr,
        )

    pnl_net = pnl_gross - fee_in - fee_out - slip - funding_paid

    # Exit reason — end_of_data when signal's exit_us is beyond last bar
    exit_reason = np.where(exit_idx >= n_bars, "end_of_data", "time_stop")

    trades_df = pd.DataFrame({
        "asset": asset,
        "direction": sig["direction"].to_numpy(),
        "signal_us": sig["signal_us"].to_numpy(),
        "entry_us": entry_us_arr,
        "entry_price": entry_price,
        "exit_us": exit_us_arr,
        "exit_price": exit_price,
        "notional_usd": notional_arr,
        "leverage": lev_arr,
        "fee_in_usd": fee_in,
        "fee_out_usd": fee_out,
        "slippage_usd": slip,
        "funding_paid_usd": funding_paid,
        "pnl_gross_usd": pnl_gross,
        "pnl_net_usd": pnl_net,
        "bars_held": bars_held,
        "exit_reason": exit_reason,
    })
    trades_df = trades_df.loc[valid].reset_index(drop=True)

    stats = _summary_stats(trades_df, asset)
    return trades_df, stats


def _vectorized_funding(
    fnd: pd.DataFrame,
    entry_us_arr: np.ndarray,
    exit_us_arr: np.ndarray,
    pos_notional_arr: np.ndarray,
    dir_sign_arr: np.ndarray,
    cap_bps_hr: float,
) -> np.ndarray:
    """Vectorized: for each trade, sum capped funding rates over its lifetime.

    Builds a cumulative sum of capped rates indexed by funding_time_us, then
    looks up cumsum at entry & exit timestamps; difference × pos_notional ×
    direction = funding paid.
    """
    cap_frac = float(cap_bps_hr) / 10_000.0
    times = fnd["funding_time_us"].to_numpy()
    rates_capped = fnd["funding_rate"].clip(lower=-cap_frac, upper=+cap_frac).to_numpy()
    # cumsum [0, r0, r0+r1, ...] so cumsum[k] = sum of first k rates
    csum = np.concatenate(([0.0], np.cumsum(rates_capped)))
    # For interval [entry, exit), we want indices [searchsorted(times,entry,'left'),
    #                                              searchsorted(times,exit,'left'))
    lo = np.searchsorted(times, entry_us_arr, side="left")
    hi = np.searchsorted(times, exit_us_arr, side="left")
    rate_sums = csum[hi] - csum[lo]   # sum of rates falling in [entry, exit)
    return dir_sign_arr * pos_notional_arr * rate_sums


def _summary_stats(trades_df: pd.DataFrame, asset: str) -> dict:
    """Compute summary stats from a trades DataFrame."""
    n = len(trades_df)
    if n == 0:
        return {
            "asset": asset, "n_trades": 0, "n_wins": 0,
            "win_rate": float("nan"), "total_pnl_usd": 0.0,
            "avg_pnl_usd": float("nan"), "sharpe": float("nan"),
            "max_dd_usd": 0.0, "avg_funding_paid": 0.0,
            "avg_fees_paid": 0.0, "avg_bars_held": float("nan"),
            "n_end_of_data": 0,
        }
    pnl = trades_df["pnl_net_usd"].to_numpy()
    wins = (pnl > 0).sum()
    sharpe = float("nan")
    if pnl.std() > 0:
        sharpe = float((pnl.mean() / pnl.std()) * np.sqrt(252))
    # Max-DD on cumulative net PnL
    cum = np.cumsum(pnl)
    peaks = np.maximum.accumulate(cum)
    dd = cum - peaks
    max_dd = float(dd.min()) if len(dd) else 0.0
    n_eod = int((trades_df["exit_reason"] == "end_of_data").sum())
    return {
        "asset": asset,
        "n_trades": int(n),
        "n_wins": int(wins),
        "win_rate": float(wins) / n,
        "total_pnl_usd": float(pnl.sum()),
        "avg_pnl_usd": float(pnl.mean()),
        "sharpe": sharpe,
        "max_dd_usd": max_dd,
        "avg_funding_paid": float(trades_df["funding_paid_usd"].mean()),
        "avg_fees_paid": float((trades_df["fee_in_usd"] + trades_df["fee_out_usd"]).mean()),
        "avg_bars_held": float(trades_df["bars_held"].mean()),
        "n_end_of_data": n_eod,
    }


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path

    REPO = Path(__file__).resolve().parent.parent.parent
    BTC_KLINE = REPO / "data" / "binance" / "parquet" / "BTCUSDT" / "1h" / "year=2025" / "part.parquet"
    BTC_FUNDING = REPO / "data" / "hyperliquid" / "funding" / "BTC_funding.parquet"

    if not BTC_KLINE.exists():
        sys.exit(f"BTC kline not found at {BTC_KLINE}")
    if not BTC_FUNDING.exists():
        sys.exit(f"BTC funding not found at {BTC_FUNDING}")

    klines = pd.read_parquet(BTC_KLINE)
    funding = pd.read_parquet(BTC_FUNDING)
    print(f"Loaded {len(klines)} BTC 1h klines, range "
          f"{klines['open_time'].min()} -> {klines['open_time'].max()}")
    print(f"Loaded {len(funding)} BTC funding rows, range "
          f"{funding.index.min()} -> {funding.index.max()}")

    # Normalize + restrict to overlap window
    kl = _ensure_open_time_us(klines)
    fnd = _ensure_funding_us(funding)
    overlap_lo = max(kl["open_time_us"].min(), fnd["funding_time_us"].min())
    overlap_hi = min(kl["open_time_us"].max(), fnd["funding_time_us"].max())
    print(f"Overlap window: us={overlap_lo}..{overlap_hi}")

    # Generate 100 random LONG signal timestamps inside overlap
    rng = np.random.default_rng(42)
    times = kl["open_time_us"].to_numpy()
    in_window = (times >= overlap_lo) & (times <= overlap_hi - 24 * 3_600_000_000)
    candidate = times[in_window]
    if len(candidate) < 100:
        print(f"WARN: only {len(candidate)} candidate bars in overlap window")
    sample_n = min(100, len(candidate))
    chosen = rng.choice(candidate, size=sample_n, replace=False)
    chosen.sort()

    # Build signals at three configs
    def make_signals(hold_hours: int, direction: str = "LONG") -> pd.DataFrame:
        return pd.DataFrame({
            "signal_us": chosen,
            "direction": [direction] * sample_n,
            "exit_us": chosen + hold_hours * 3_600_000_000,
        })

    cfg = HyperliquidConfig()
    print("\n--- HyperliquidConfig defaults ---")
    print(cfg)

    for hold_h, lev in [(1, 1.0), (1, 3.0), (24, 1.0), (24, 3.0)]:
        sig = make_signals(hold_h, "LONG")
        trades_df, stats = run_backtest(
            kl, fnd, sig, "BTC",
            notional_usd=250.0, leverage=lev, cfg=cfg,
        )
        print(f"\n=== hold={hold_h}h lev={lev}x n={stats['n_trades']} ===")
        print(f"  win_rate     : {stats['win_rate']:.3f}")
        print(f"  total_pnl    : ${stats['total_pnl_usd']:+.2f}")
        print(f"  avg_pnl      : ${stats['avg_pnl_usd']:+.4f}")
        print(f"  sharpe       : {stats['sharpe']:.3f}")
        print(f"  max_dd       : ${stats['max_dd_usd']:+.2f}")
        print(f"  avg_funding  : ${stats['avg_funding_paid']:+.4f}")
        print(f"  avg_fees     : ${stats['avg_fees_paid']:+.4f}")
        print(f"  bars_held    : {stats['avg_bars_held']:.2f}")

    # Sanity test: zero-drift -> net PnL ~ -2*fee - slippage - funding
    print("\n--- Sanity: zero-drift fake klines, expected net ~= -(2*fee + slip + funding) ---")
    fake = kl.iloc[:200].copy()
    fake["open"] = 100000.0
    fake["high"] = 100000.0
    fake["low"]  = 100000.0
    fake["close"] = 100000.0
    sig = pd.DataFrame({
        "signal_us": [int(fake["open_time_us"].iloc[10])],
        "direction": ["LONG"],
        "exit_us":   [int(fake["open_time_us"].iloc[11])],
    })
    tdf, st = run_backtest(fake, fnd, sig, "BTC",
                           notional_usd=250.0, leverage=1.0, cfg=cfg)
    if st["n_trades"] >= 1:
        t = tdf.iloc[0]
        expected_drag = -(t["fee_in_usd"] + t["fee_out_usd"] + t["slippage_usd"] + t["funding_paid_usd"])
        print(f"  fee_in        : ${t['fee_in_usd']:+.4f}")
        print(f"  fee_out       : ${t['fee_out_usd']:+.4f}")
        print(f"  slippage      : ${t['slippage_usd']:+.4f}")
        print(f"  funding       : ${t['funding_paid_usd']:+.4f}")
        print(f"  pnl_gross     : ${t['pnl_gross_usd']:+.6f}")
        print(f"  pnl_net       : ${t['pnl_net_usd']:+.4f}")
        print(f"  expected_drag : ${expected_drag:+.4f}")
        ok = abs(t["pnl_net_usd"] - expected_drag) < 1e-6
        print(f"  match (<=1e-6): {ok}")
    else:
        print("  no trade — funding range may not cover BTC kline range")
