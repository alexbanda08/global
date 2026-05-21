"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""
Shared backtest harness for strategy-discovery session 2026-05-16.

Conventions enforced (anti-footgun):
  * All times: UTC microseconds.
  * outcome truth: chainlink (from load_resolutions default).
  * fee: 2% on profit only.
  * Entry at flexible `entry_us` -- callers pass it. No implicit ws_s+120.

Function `evaluate_signal(predictions, *, entry_offset_s=None, entry_anchor='ws_s')`
  predictions: DataFrame with columns [slug, ticker, timeframe, slot_start_us, outcome, signal]
               signal in {"UP","DOWN","SKIP"}.
  entry_anchor: 'ws_s' (then entry_us = (ws_s + entry_offset_s)*1e6)
                'slot_start' (then entry_us = slot_start_us + entry_offset_s*1e6)
                'slot_end_minus' (then entry_us = slot_end_us - entry_offset_s*1e6)
  Returns dict with hit_rate, total_pnl, n_trades, ...
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (  # type: ignore
    load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
    asof_strict, slug_to_ws_s,
)

# ----- Constants -----
NOTIONAL = 25.0
FEE_RATE = 0.02              # on profit only (legacy momo model)
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
WINDOW_S = {"5m": 300, "15m": 900}

# Cache for kline arrays
_KLINE_CACHE: dict[tuple[str, str, str], tuple[np.ndarray, np.ndarray]] = {}


def get_klines(asset: str, venue: str = "binance-spot-ws", period: str = "1MIN"):
    """Return (end_us, prices) arrays, cached."""
    key = (asset.upper(), venue, period)
    if key not in _KLINE_CACHE:
        _KLINE_CACHE[key] = load_klines_asof(asset.upper(), venue, period)
    return _KLINE_CACHE[key]


def compute_entry_us(row, anchor: str, offset_s: float) -> int:
    """Compute entry_us from a row + anchor + offset (seconds)."""
    if anchor == "ws_s":
        ws_s = slug_to_ws_s(row["slug"], row["timeframe"])
        return int((ws_s + offset_s) * 1_000_000)
    if anchor == "slot_start":
        return int(row["slot_start_us"] + offset_s * 1_000_000)
    if anchor == "slot_end_minus":
        return int(row["slot_end_us"] - offset_s * 1_000_000)
    raise ValueError(f"unknown anchor {anchor}")


def hold_pnl_no_book(signal: str, outcome: str, entry_price: float, notional: float = NOTIONAL) -> float:
    """PnL assuming you bought YES on signal-side at entry_price, hold to settlement.
    Settlement = 1 if signal matches outcome else 0.
    Shares = notional / entry_price.
    Profit = shares*(settle - entry_price). Fee = 2% on positive profit only.
    """
    if entry_price <= 0 or entry_price >= 1:
        return 0.0
    shares = notional / entry_price
    won = (signal.upper() == outcome.upper())
    settle = 1.0 if won else 0.0
    profit = shares * (settle - entry_price)
    fee = max(profit, 0.0) * FEE_RATE
    return profit - fee


def get_book_at(books: dict, slug: str, outcome_side: str, ts_us: int):
    """Look up L25 book snapshot at-or-before ts_us. Returns (ap, asz, bp, bsz) or None."""
    key = (slug, outcome_side)
    if key not in books:
        return None
    ts, ap, asz, bp, bsz = books[key]
    i = int(np.searchsorted(ts, ts_us, side="right") - 1)
    if i < 0:
        return None
    return ap[i], asz[i], bp[i], bsz[i]


def walk_asks(prices, sizes, dollars: float = NOTIONAL):
    """Walk ask book for `dollars`, return (vwap, shares, usd_spent, under_filled)."""
    prices = np.asarray(prices, dtype=float)
    sizes = np.asarray(sizes, dtype=float)
    spent = 0.0
    shares = 0.0
    for p, s in zip(prices, sizes):
        if not np.isfinite(p) or p <= 0 or s <= 0:
            continue
        cost_full = p * s
        if spent + cost_full >= dollars:
            need = (dollars - spent) / p
            shares += need
            spent += need * p
            return spent / shares, shares, spent, False
        shares += s
        spent += cost_full
    under = spent < dollars * 0.5
    if shares <= 0:
        return np.nan, 0.0, 0.0, True
    return spent / shares, shares, spent, under


def book_fill_pnl(
    slug: str, signal: str, outcome: str,
    books_btc: dict | None, books_eth: dict | None, books_sol: dict | None,
    ts_us: int, asset: str, notional: float = NOTIONAL,
):
    """Fill at L25 book on signal-side, hold to settlement. Returns (pnl, vwap, under)."""
    if signal.upper() not in ("UP", "DOWN"):
        return 0.0, np.nan, True
    side = "Up" if signal.upper() == "UP" else "Down"
    books = {"BTC": books_btc, "ETH": books_eth, "SOL": books_sol}[asset.upper()]
    if books is None:
        return 0.0, np.nan, True
    snap = get_book_at(books, slug, side, ts_us)
    if snap is None:
        return 0.0, np.nan, True
    ap, asz, bp, bsz = snap
    # Spread filter
    if np.isfinite(ap[0]) and np.isfinite(bp[0]):
        if (ap[0] - bp[0]) > SPREAD_FILTER[asset.upper()]:
            return 0.0, ap[0], True
    vwap, shares, spent, under = walk_asks(ap, asz, notional)
    if under or not np.isfinite(vwap):
        return 0.0, vwap, True
    pnl = hold_pnl_no_book(signal, outcome, vwap, notional=notional)
    return pnl, vwap, False


def evaluate_no_book(
    df: pd.DataFrame,
    *,
    entry_anchor: str = "ws_s",
    entry_offset_s: float = 120.0,
    fixed_entry_price: float = 0.5,
):
    """Quick evaluation w/o book fills (uses flat entry_price for PnL estimate).
    Returns hit_rate / pnl_total / n_trades / per-asset breakdown.
    Use this to triage signals fast before paying L25 cost.
    """
    fired = df[df["signal"].isin(("UP", "DOWN"))].copy()
    if len(fired) == 0:
        return {"n_trades": 0, "hit_rate": np.nan, "pnl_total": np.nan}
    fired["won"] = (fired["signal"].str.upper() == fired["outcome"].str.upper()).astype(int)
    hit = fired["won"].mean()
    fired["pnl"] = fired.apply(
        lambda r: hold_pnl_no_book(r["signal"], r["outcome"], fixed_entry_price), axis=1
    )
    pnl_total = fired["pnl"].sum()
    per_asset = (
        fired.groupby(["ticker", "timeframe"])
             .agg(n=("won", "size"), hit=("won", "mean"), pnl=("pnl", "sum"))
             .round(4)
    )
    return {
        "n_trades": int(len(fired)),
        "hit_rate": float(hit),
        "pnl_total": float(pnl_total),
        "per_asset": per_asset,
        "fired": fired,
    }


def load_book_subset(asset: str, slugs: set[str]):
    """Load L25 books for a slug subset, suppressing logs."""
    if not slugs:
        return {}
    return load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=True)


if __name__ == "__main__":
    # Smoke test
    res = load_resolutions(assets=["BTC"], timeframes=["5m"]).head(200)
    res["signal"] = "UP"   # constant baseline
    r = evaluate_no_book(res, fixed_entry_price=0.5)
    print(f"smoke: n={r['n_trades']} hit={r['hit_rate']:.3f} pnl_at_0.5={r['pnl_total']:.2f}")
