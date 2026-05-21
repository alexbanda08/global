"""
engine_v2.py — live-mimic backtest primitives. Single source of truth.

Combines the four steals from `evan-kolberg/prediction-market-backtesting`
(see EXTERNAL_REPO_COMPARISON_evan_kolberg_pmxt_2026_05_12.md) into a
self-contained engine that mimics live Polymarket-WS production fills:

  1. LATENCY  — order arrives at book `LATENCY_MS` after decision (PMXT default 85ms).
  2. FEES     — real Polymarket taker fee curve `feeRate × p × (1-p)`, on EVERY fill
                (BOTH legs, not "2% on profit only" shortcut).
  3. SPARSE-BOOK FILTER — drop markets with `< MIN_BOOK_EVENTS` snapshots in window.
  4. STRICT-ASOF BOOK LOOKUP — no future leak (matches production WS controller).

## Usage in any backtest

```python
from strategy_lab.engine_v2 import (
    EngineConfig, LegacyConfig, LiveMimicConfig,
    fill_at_book, hold_pnl, sell_pnl_partial,
)

cfg = LiveMimicConfig()           # 7% poly fee on every fill + 85ms latency
# cfg = LegacyConfig()            # backward-compat: 2%-on-profit, 0ms latency

fill = fill_at_book(books_idx, slug, outcome="Up", fire_us=r["ws"]*1e6, cfg=cfg)
if fill is None: continue
pnl = hold_pnl(fill, won=(r["signal"]=="UP" and r["outcome"]=="Up"), cfg=cfg)
```

## Why this exists

The old `momo_full_universe_validation.simulate_trade` has `FEE=0.02` hardcoded
as `profit * FEE if profit > 0 else 0.0` in 4 places — the legacy 2%-on-profit
shortcut. To run a backtest that mimics what live-WS production will see, we
need to:
  - charge fees on the losing leg too (poly does)
  - charge a price-dependent fee, not flat 2%
  - shift book lookup by ~85ms so we don't get pre-decision snapshots

This module provides those primitives. New backtests should use this directly;
old ones can be migrated piece by piece.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Callable

import numpy as np

# Make sibling modules importable regardless of how this is invoked
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.insert(0, str(_HERE))

from book_walk import book_walk_fill  # noqa: E402
from fees import poly_taker_fee_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS  # noqa: E402
from latency import DEFAULT_LATENCY, apply_latency, StaticLatencyConfig  # noqa: E402

NOTIONAL_DEFAULT: float = 25.0
DEFAULT_MAX_BOOK_STALENESS_US: int = 60_000_000   # 60s — production tolerates this


# ---------------------------------------------------------------------------
# Engine config dataclass — toggleable between legacy and live-mimic mode
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineConfig:
    """Backtest engine config. Choose `LegacyConfig()` or `LiveMimicConfig()`."""
    name: str = "custom"
    notional_usd: float = NOTIONAL_DEFAULT
    # Latency: shift between `decision_us` (fire) and `lookup_us` (book read).
    latency_ms: float = 0.0
    latency_cfg: StaticLatencyConfig = field(default_factory=lambda: DEFAULT_LATENCY)
    apply_latency_to_entry: bool = False
    apply_latency_to_exit: bool = False
    # Fees:
    #   "legacy_2pct_on_profit"  — historical shortcut: 2% × profit, only if profit>0
    #   "poly_taker_curve"       — real Polymarket: feeRate × p × (1-p) per share, every fill
    fee_model: str = "legacy_2pct_on_profit"
    poly_fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)   # 0.07 for crypto markets
    legacy_fee_pct: float = 0.02
    # Sparse-book filter:
    min_book_events: int = 0       # 0 disables; PMXT default = 25
    # Book staleness:
    max_book_staleness_us: int = DEFAULT_MAX_BOOK_STALENESS_US


@dataclass(frozen=True)
class LegacyConfig(EngineConfig):
    """Reproduces every backtest written before 2026-05-16. Use for comparison."""
    name: str = "legacy"
    fee_model: str = "legacy_2pct_on_profit"
    latency_ms: float = 0.0
    apply_latency_to_entry: bool = False
    apply_latency_to_exit: bool = False
    min_book_events: int = 0


@dataclass(frozen=True)
class LiveMimicConfig(EngineConfig):
    """Mimics what live-WS production will see post-TV-agent migration.

    Differences from legacy:
      - charges real Polymarket fee `0.07 × p × (1-p)` on every fill
      - shifts book lookup by `latency_cfg.effective_fill_ms` (default 85ms)
      - drops markets with < 25 book events in window
    """
    name: str = "live_mimic"
    fee_model: str = "poly_taker_curve"
    latency_ms: float = 85.0
    apply_latency_to_entry: bool = True
    apply_latency_to_exit: bool = True
    min_book_events: int = 25


# ---------------------------------------------------------------------------
# Book lookup primitive — strict asof, optionally with latency shift
# ---------------------------------------------------------------------------

def find_book_strict(
    books_idx: dict,
    slug_or_mid: str,
    outcome: str,
    target_us: int,
    *,
    max_staleness_us: int = DEFAULT_MAX_BOOK_STALENESS_US,
):
    """STRICT asof — returns latest book snapshot with ts <= target_us.

    NEVER returns a future snap. Matches production WS controller semantics.
    Returns dict {ap, asz, bp, bsz, ts_us, dt_us} or None if no valid snap.
    """
    rec = books_idx.get((slug_or_mid, outcome))
    if rec is None:
        return None
    ts, ap, asz, bp, bs = rec
    if len(ts) == 0:
        return None
    pos = int(np.searchsorted(ts, int(target_us), side="right"))
    if pos == 0:
        return None
    i = pos - 1
    dt = int(target_us) - int(ts[i])
    if dt > max_staleness_us:
        return None
    return {
        "ap": ap[i], "asz": asz[i], "bp": bp[i], "bsz": bs[i],
        "ts_us": int(ts[i]), "dt_us": dt,
    }


def book_event_count(books_idx: dict, slug: str, outcome: str,
                     start_us: int, end_us: int) -> int:
    """Count snapshots in [start_us, end_us] for the (slug, outcome) pair."""
    rec = books_idx.get((slug, outcome))
    if rec is None:
        return 0
    ts = rec[0]
    if len(ts) == 0:
        return 0
    return int(((ts >= int(start_us)) & (ts <= int(end_us))).sum())


# ---------------------------------------------------------------------------
# Fee primitive — switches between legacy and poly_taker_curve
# ---------------------------------------------------------------------------

def fill_commission_usd(
    vwap: float,
    shares: float,
    *,
    is_winning_leg: bool,
    cfg: EngineConfig,
) -> float:
    """Per-fill commission in USD. Sign convention: positive = paid by trader.

    - legacy_2pct_on_profit: charged on WINNING leg only, as 2% × (profit_usd).
      Caller passes profit_usd via shares and vwap (shares × (1 - vwap) for winners).
      This branch returns commission = 0 unless is_winning_leg=True.
    - poly_taker_curve: per-share fee `feeRate × vwap × (1-vwap)`, ALWAYS charged.
    """
    if cfg.fee_model == "poly_taker_curve":
        return float(shares) * poly_taker_fee_per_share(vwap, cfg.poly_fee_rate)
    if cfg.fee_model == "legacy_2pct_on_profit":
        if not is_winning_leg:
            return 0.0
        profit = float(shares) * (1.0 - float(vwap))
        return profit * cfg.legacy_fee_pct if profit > 0 else 0.0
    raise ValueError(f"unknown fee_model {cfg.fee_model!r}")


# ---------------------------------------------------------------------------
# Composite primitive — fill at book with latency + spread filter
# ---------------------------------------------------------------------------

def fill_at_book(
    books_idx: dict,
    slug_or_mid: str,
    outcome: str,
    fire_us: int,
    *,
    cfg: EngineConfig,
    side: str = "buy",
    spread_filter: float | None = None,
    notional_usd: float | None = None,
) -> dict | None:
    """Live-mimic taker fill: latency-shifted strict-asof book → walk for notional.

    Returns dict with keys: vwap, shares, usd, fee_in, levels, ts_us, dt_us, ask0, bid0
    Or None if: no book / stale book / spread too wide / under-filled.

    `cfg.apply_latency_to_entry` controls whether to shift fire_us by latency.
    Pass `spread_filter` (e.g. 0.02) to drop wide-spread markets; None disables.
    """
    if cfg.apply_latency_to_entry and cfg.latency_ms > 0:
        lookup_us = int(fire_us) + int(cfg.latency_ms * 1_000)
    else:
        lookup_us = int(fire_us)

    book = find_book_strict(books_idx, slug_or_mid, outcome, lookup_us,
                            max_staleness_us=cfg.max_book_staleness_us)
    if book is None:
        return None
    ap, asz = book["ap"], book["asz"]
    bp = book["bp"]

    ask0 = float(ap[0]) if (len(ap) and math.isfinite(ap[0])) else float("nan")
    bid0 = float(bp[0]) if (len(bp) and math.isfinite(bp[0])) else float("nan")
    if spread_filter is not None and math.isfinite(ask0) and math.isfinite(bid0):
        if (ask0 - bid0) > spread_filter:
            return None

    notional = cfg.notional_usd if notional_usd is None else float(notional_usd)
    vwap, shares, usd, levels, under = book_walk_fill(
        [float(x) for x in ap], [float(x) for x in asz], notional,
        side=side,
    )
    if shares <= 0 or (under and usd < notional * 0.5):
        return None
    # entry fee — only meaningful for the poly_taker_curve model
    fee_in = (shares * poly_taker_fee_per_share(vwap, cfg.poly_fee_rate)
              if cfg.fee_model == "poly_taker_curve" else 0.0)
    return {
        "vwap": vwap, "shares": shares, "usd": usd, "fee_in": fee_in,
        "levels": levels, "ts_us": book["ts_us"], "dt_us": book["dt_us"],
        "ask0": ask0, "bid0": bid0,
    }


# ---------------------------------------------------------------------------
# PnL primitives
# ---------------------------------------------------------------------------

def hold_pnl(fill: dict, *, won: bool, cfg: EngineConfig) -> float:
    """P&L from holding a $`fill['usd']` long position to settlement.

    Settlement = $1.00 if won, $0.00 if lost.
    """
    shares = float(fill["shares"])
    usd_in = float(fill["usd"])
    if won:
        gross = shares * 1.0 - usd_in
        if cfg.fee_model == "poly_taker_curve":
            # entry fee already charged at fill (fee_in). Settlement has no fee.
            return gross - float(fill.get("fee_in", 0.0))
        else:  # legacy_2pct_on_profit
            return gross - (gross * cfg.legacy_fee_pct if gross > 0 else 0.0)
    # lost
    if cfg.fee_model == "poly_taker_curve":
        # paid entry fee + lost the principal
        return -usd_in - float(fill.get("fee_in", 0.0))
    else:
        return -usd_in     # legacy: no fee on loss


def sell_at_bid_partial(bid_p, bid_s, shares: float) -> tuple[float, float, float]:
    """Walk the bid side for up to `shares`. Returns (vwap, shares_sold, usd_received)."""
    remaining = float(shares); total_usd = 0.0; total_shares = 0.0
    for p, s in zip(bid_p, bid_s):
        try:
            p = float(p); s = float(s)
        except (TypeError, ValueError):
            break
        if not (math.isfinite(p) and math.isfinite(s)) or s <= 0 or p <= 0 or p >= 1:
            break
        if s >= remaining:
            total_usd += remaining * p; total_shares += remaining; remaining = 0; break
        total_usd += s * p; total_shares += s; remaining -= s
    if total_shares <= 0:
        return 0.0, 0.0, 0.0
    return total_usd / total_shares, total_shares, total_usd


def sell_pnl(
    fill: dict,
    sell_vwap: float,
    sell_shares: float,
    sell_usd: float,
    *,
    cfg: EngineConfig,
) -> float:
    """P&L from selling shares at `sell_vwap`. Fee on the sell leg per cfg.

    Entry cost = fill['usd'] (already paid + entry fee if poly_taker_curve).
    Sell leg charges its own fee on `sell_usd` notional via the curve.
    """
    usd_in = float(fill["usd"])
    if cfg.fee_model == "poly_taker_curve":
        fee_out = float(sell_shares) * poly_taker_fee_per_share(sell_vwap, cfg.poly_fee_rate)
        return float(sell_usd) - usd_in - float(fill.get("fee_in", 0.0)) - fee_out
    else:
        profit = float(sell_usd) - usd_in
        return profit - (profit * cfg.legacy_fee_pct if profit > 0 else 0.0)


# ---------------------------------------------------------------------------
# Smoke test — confirms fees + latency wire through
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Hypothetical fill: 36.2 shares @ $0.69 vwap = $25 spend
    fill_legacy = {"shares": 36.2, "usd": 25.0, "vwap": 0.69, "fee_in": 0.0}
    fill_lm     = {"shares": 36.2, "usd": 25.0, "vwap": 0.69,
                   "fee_in": 36.2 * poly_taker_fee_per_share(0.69)}

    print(f"=== fee_in (poly curve at p=0.69):  ${fill_lm['fee_in']:.4f}")
    print(f"    (vs legacy fee_in: ${fill_legacy['fee_in']:.4f})")

    print("\n--- HOLD pnl, won ---")
    print(f"  legacy:    ${hold_pnl(fill_legacy, won=True,  cfg=LegacyConfig()):+.4f}")
    print(f"  live_mimic ${hold_pnl(fill_lm,     won=True,  cfg=LiveMimicConfig()):+.4f}")
    print("\n--- HOLD pnl, lost ---")
    print(f"  legacy:    ${hold_pnl(fill_legacy, won=False, cfg=LegacyConfig()):+.4f}")
    print(f"  live_mimic ${hold_pnl(fill_lm,     won=False, cfg=LiveMimicConfig()):+.4f}")

    # EV at p=0.69, hit=48% (corrected momo number)
    hit = 0.481
    ev_legacy = hit * hold_pnl(fill_legacy, won=True, cfg=LegacyConfig()) + \
                (1-hit) * hold_pnl(fill_legacy, won=False, cfg=LegacyConfig())
    ev_lm     = hit * hold_pnl(fill_lm, won=True, cfg=LiveMimicConfig()) + \
                (1-hit) * hold_pnl(fill_lm, won=False, cfg=LiveMimicConfig())
    print(f"\n--- EV at vwap=0.69, hit=48.1% (corrected momo number) ---")
    print(f"  legacy:    ${ev_legacy:+.4f}/trade")
    print(f"  live_mimic ${ev_lm:+.4f}/trade")
    print(f"  delta:     ${ev_lm - ev_legacy:+.4f}/trade  ← what real fees cost")

    print("\n--- latency demo ---")
    print(f"  effective_fill_ms (live_mimic): {LiveMimicConfig().latency_ms}ms")
    print(f"  fire_us=1778342400000000 → lookup_us={1778342400000000 + int(LiveMimicConfig().latency_ms*1000)}")
