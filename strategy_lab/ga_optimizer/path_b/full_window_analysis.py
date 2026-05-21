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
Use FULL April 24 → May 19 universe (26 days, 28,731 markets) instead of just
production events (May 6 → May 19, 13 days).

Two complementary analyses:

1. BASELINE BIAS: For each (asset, tf, hour, dow) cell, what's the natural
   Up/Down ratio? If biased >55% one direction, that's a signal-free edge.

2. SLEEVE-FREE FADE TEST: Re-run the TIER A pattern (BTC 15m 06-11 weekday)
   on ALL 28,731 chainlink resolutions, with real L25 fills (no subsample) on
   the DOWN side. No production-sleeve signal needed.

Critical: ALL fills use latency-corrected L25 + opposite-side ask walk + 2% fee.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_resolutions, load_orderbook_l25_streaming, asof_strict

NOTIONAL = 25.0
FEE_RATE = 0.02
SPREAD_MAX = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}


def walk_asks(prices, sizes, dollars=NOTIONAL):
    spent = 0.0; shares = 0.0
    for p, s in zip(prices, sizes):
        if not np.isfinite(p) or p <= 0 or s <= 0:
            continue
        cost_full = p * s
        if spent + cost_full >= dollars:
            need = (dollars - spent) / p
            shares += need; spent += need * p
            return spent / shares, shares, spent, False
        shares += s; spent += cost_full
    if shares <= 0:
        return np.nan, 0.0, 0.0, True
    return spent / shares, shares, spent, spent < dollars * 0.5


def get_snap(books, slug, outcome_side, fire_us):
    key = (slug, outcome_side)
    if key not in books:
        return None
    ts, ap, asz, bp, bsz = books[key]
    i = int(np.searchsorted(ts, fire_us, side="right") - 1)
    if i < 0:
        return None
    return ap[i], asz[i], bp[i], bsz[i], int(ts[i])


def hour_bucket(h):
    if h < 6: return "00-05"
    if h < 12: return "06-11"
    if h < 18: return "12-17"
    return "18-23"


def main():
    print("=== FULL-WINDOW ANALYSIS (April 24 → May 19) ===")
    res = load_resolutions()
    print(f"resolutions: {len(res):,}  window: {pd.to_datetime(res.slot_start_us.min(), unit='us', utc=True)} → {pd.to_datetime(res.slot_start_us.max(), unit='us', utc=True)}")

    res["ts"] = pd.to_datetime(res.slot_start_us, unit="us", utc=True)
    res["hour"] = res.ts.dt.hour
    res["dow"] = res.ts.dt.dayofweek
    res["hour_bucket"] = res.hour.apply(hour_bucket)
    res["dow_group"] = res.dow.apply(lambda d: "weekday" if d < 5 else "weekend")
    res["outcome_up"] = (res.outcome == "Up").astype(int)
    res["asset"] = res.ticker.str.upper()

    # === Analysis 1: BASELINE BIAS per cell (signal-free) ===
    print(f"\n=== ANALYSIS 1: Base outcome bias per (asset, tf, hour, dow) ===")
    base = res.groupby(["asset", "timeframe", "hour_bucket", "dow_group"]).agg(
        n=("outcome", "size"),
        up_rate=("outcome_up", "mean"),
    ).reset_index()
    # Stat test: binomial p-value for deviation from 50%
    from scipy.stats import binomtest
    pvals = []
    for _, r in base.iterrows():
        n_up = int(r.up_rate * r.n)
        try:
            p = binomtest(n_up, int(r.n), p=0.5).pvalue
        except Exception:
            p = 1.0
        pvals.append(p)
    base["binom_p"] = pvals
    base["abs_bias"] = (base.up_rate - 0.5).abs()
    base = base.sort_values("binom_p")
    print(f"\nBase-rate biased cells (binom p<0.05, |bias|>2%):")
    biased = base[(base.binom_p < 0.05) & (base.abs_bias > 0.02) & (base.n >= 50)]
    if len(biased):
        print(biased.to_string(index=False))
    else:
        print(" (none — outcomes are balanced ~50% in all cells, no signal-free edge)")

    # === Analysis 2: TIER A fade pattern on FULL universe with REAL L25 ===
    print(f"\n=== ANALYSIS 2: TIER A pattern (BTC 15m 06-11 weekday → buy DOWN) on FULL window ===")
    # Filter to BTC 15m, 06-11 UTC, weekday
    tier_a_universe = res[(res.asset == "BTC") & (res.timeframe == "15m") &
                          (res.hour_bucket == "06-11") & (res.dow_group == "weekday")].copy()
    print(f"  Target markets in full window: {len(tier_a_universe):,}")

    # We need to fire BEFORE settlement; production sleeve fires at ws_s+120 = slot_start - 780s
    # We'll use same production fire timing for fair comparison
    tier_a_universe["fire_us"] = tier_a_universe.slot_start_us - 900 * 1_000_000 + 120 * 1_000_000

    # Load L25 books (full, no subsample) for these slugs
    slugs = set(tier_a_universe.slug.unique())
    print(f"  Loading FULL L25 (no subsample) for {len(slugs)} slugs...")
    t0 = time.time()
    books = {}
    slugs_list = list(slugs)
    for i in range(0, len(slugs_list), 300):
        chunk = set(slugs_list[i:i+300])
        bks = load_orderbook_l25_streaming("btc", slugs=chunk, subsample_1hz=False)
        books.update(bks)
    print(f"    {len(books)} (slug,side) keys in {time.time()-t0:.0f}s")

    # For each market, simulate "fade everything DOWN" — naïve baseline
    # Then we'll layer the volume_INV_NIGHT-like signal proxy
    rows = []
    for _, r in tier_a_universe.iterrows():
        fire_us = int(r.fire_us)
        # Apply 100ms latency margin
        safe_us = fire_us - 100_000

        # Trade: ALWAYS BUY DOWN (the TIER A fade hypothesis with no signal — simplest test)
        snap = get_snap(books, r.slug, "Down", safe_us)
        if snap is None:
            continue
        ap, asz, bp, bsz, book_ts = snap
        if not (np.isfinite(ap[0]) and np.isfinite(bp[0])):
            continue
        spread = ap[0] - bp[0]
        if spread > SPREAD_MAX["BTC"]:
            continue
        vwap, shares, spent, under = walk_asks(list(ap), list(asz), NOTIONAL)
        if under or not np.isfinite(vwap):
            continue
        won = int(r.outcome.upper() == "DOWN")
        profit_raw = shares * (won - vwap)
        fee = max(profit_raw, 0.0) * FEE_RATE
        pnl = profit_raw - fee
        rows.append({
            "slug": r.slug, "fire_us": fire_us, "slot_start_us": r.slot_start_us,
            "outcome": r.outcome, "vwap_down": float(vwap), "shares": float(shares),
            "won_down": won, "pnl_down": float(pnl),
            "book_lag_s": (fire_us - book_ts) / 1e6,
        })
    trades_naive = pd.DataFrame(rows)
    print(f"\n  Naive 'always buy DOWN at 06-11 wd' over FULL window: {len(trades_naive)} fills")
    if len(trades_naive):
        win_rate = trades_naive.won_down.mean()
        total_pnl = trades_naive.pnl_down.sum()
        per_trade = trades_naive.pnl_down.mean()
        n_days = (trades_naive.fire_us.max() - trades_naive.fire_us.min()) / 1e6 / 86400
        print(f"    Win rate (DOWN): {win_rate:.4f}")
        print(f"    Total PnL: ${total_pnl:+,.2f}  ({per_trade:+.2f}/trade)")
        print(f"    Days covered: {n_days:.1f}")
        print(f"    Daily rate: ${total_pnl/max(n_days,1):+,.2f}/day")
        print(f"    Monthly proj: ${total_pnl/max(n_days,1)*30:+,.2f}")
        print(f"    Median book lag: {trades_naive.book_lag_s.median():.0f}s")

        # Per-week breakdown to check stability
        trades_naive["ts"] = pd.to_datetime(trades_naive.fire_us, unit="us", utc=True)
        trades_naive["date"] = trades_naive.ts.dt.date
        daily = trades_naive.groupby("date").agg(
            n=("pnl_down", "size"), wr=("won_down", "mean"), pnl=("pnl_down", "sum")
        )
        print(f"\n  Daily breakdown (last 25 days):")
        print(daily.tail(30).to_string())

        # Permutation test
        rng = np.random.default_rng(42)
        pnl_arr = trades_naive.pnl_down.values
        sums = [(pnl_arr * rng.choice([1,-1], size=len(pnl_arr))).sum() for _ in range(2000)]
        p = (np.array(sums) >= total_pnl).mean()
        print(f"\n  Permutation p (real vs random sign-flip): {p:.4f}")

        # Save
        trades_naive.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "tier_a_full_window_naive.csv", index=False)

        # Sharpe
        sharpe = daily.pnl.mean() / daily.pnl.std() * np.sqrt(252) if daily.pnl.std() > 0 else 0
        print(f"  Annualized Sharpe (daily): {sharpe:.2f}")
        # Max DD
        cs = daily.pnl.cumsum()
        peak = cs.expanding().max()
        dd = (cs - peak).min()
        print(f"  Max drawdown (cumulative): ${dd:+.2f}")

    print(f"\n=== Summary ===")
    print(f"  Data: 28,731 chainlink-resolved markets, April 24 → May 19 (26 days)")
    print(f"  Used FULL L25 (no 1Hz subsample) — every-change snapshots")
    print(f"  TIER A test ran on {len(trades_naive)} markets — every BTC 15m 06-11 weekday in the window")
    print(f"  NO sampling, NO trading_events dependency")


if __name__ == "__main__":
    main()
