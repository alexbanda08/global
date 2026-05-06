"""verify_lookahead_bug — quantifies the rev_bp lookahead bug in the momo backtest.

The bug: extended_backtest_with_robustness.simulate() uses
    a_now = asof(k1m, ws + bucket * 10)
where asof returns the price_close of a 1MIN bar whose ts_s (open time) ≤ ts.
But that bar's close happens at ts_s + 60 — i.e., up to 60s in the future.

For a 5m market with monitoring window [ws+130, ws+290]:
    bucket 13 (ws+130) reads price at ws+180  → 50s lookahead
    bucket 25 (ws+250) reads price at ws+300  → 50s lookahead = MARKET RESOLUTION
    bucket 29 (ws+290) reads price at ws+300  → 10s lookahead = MARKET RESOLUTION

The last 5 buckets (25-29) read THE RESOLUTION PRICE itself. Backtest sees
the answer → triggers HEDGE/SELL with perfect foresight in last 50s.

This compares:
    1. The current backtest's `asof` (open-time-indexed → leaks 0-60s future)
    2. A correct `asof_strict` (end-time-indexed → strictly past data only)

For each shadow-matched trade, recomputes rev_bp triggers under both schemes
and counts trigger-time differences.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from extended_backtest_with_robustness import load_klines, asof  # noqa: E402

REV_BP = 5
MAX_BUCKET = {"5m": 29, "15m": 89}


def asof_strict(k1m: pd.DataFrame, ts: int) -> float:
    """Return price_close of the most recent COMPLETED 1MIN bar (end_time ≤ ts).

    Production-faithful: only past-closed-bar data, no lookahead.
    """
    if "time_period_end_us" not in k1m.columns:
        # Reconstruct end from start + 60s for 1MIN
        end_us = (k1m["ts_s"].astype("int64") + 60).values * 1_000_000
    else:
        end_us = k1m["time_period_end_us"].values
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if idx < 0:
        return float("nan")
    return float(k1m.price_close.iloc[idx])


def count_triggers(
    k1m: pd.DataFrame,
    ws: int,
    sig: int,  # 1=UP, 0=DOWN
    tf: str,
    asof_fn,
) -> tuple[int, int]:
    """Return (first_trigger_bucket, n_triggers) under the given asof.
    first_trigger_bucket = -1 if no trigger fires.
    """
    asset_at_entry = asof_fn(k1m, ws + 120)
    if not (asset_at_entry and np.isfinite(asset_at_entry)):
        return -1, 0
    max_b = MAX_BUCKET[tf]
    first = -1
    n = 0
    for bucket in range(13, max_b + 1):
        ts = ws + bucket * 10
        a_now = asof_fn(k1m, ts)
        if not np.isfinite(a_now):
            continue
        bp_rev = (a_now - asset_at_entry) / asset_at_entry * 10000.0
        trig = (sig == 1 and bp_rev <= -REV_BP) or (sig == 0 and bp_rev >= REV_BP)
        if trig:
            n += 1
            if first == -1:
                first = bucket
    return first, n


def main():
    print("[1] loading klines…")
    klines = load_klines()

    print("[2] loading shadow matched trades…")
    pertrade = pd.read_csv(
        ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_shadow_match.csv"
    )
    matched = pertrade[pertrade["matched"] == True].copy()  # noqa: E712
    print(f"    {len(matched)} matched trades")

    print("[3] running both asof variants on each match…")
    rows = []
    for _, row in matched.iterrows():
        asset = row["asset"].lower()
        tf = row["timeframe"]
        ws = int(row["ws_unix"])
        sig = 1 if row["signal"] == "UP" else 0

        k = klines[asset]

        # Buggy version (current backtest)
        first_buggy, n_buggy = count_triggers(k, ws, sig, tf, asof)
        # Strict (no lookahead)
        first_strict, n_strict = count_triggers(k, ws, sig, tf, asof_strict)

        rows.append({
            "slug": row["slug"],
            "asset": row["asset"],
            "tf": tf,
            "exit": row["exit"],
            "first_trigger_buggy": first_buggy,
            "first_trigger_strict": first_strict,
            "n_triggers_buggy": n_buggy,
            "n_triggers_strict": n_strict,
            "delta_first": (first_strict - first_buggy)
                            if (first_buggy >= 0 and first_strict >= 0) else None,
        })
    df = pd.DataFrame(rows)
    out_csv = ROOT / "strategy_lab" / "results" / "meta_classifier" / "lookahead_bug_audit.csv"
    df.to_csv(out_csv, index=False)
    print(f"    [csv] → {out_csv}")

    # ---- Stats ----
    print("\n[4] summary by tf:")
    for tf in ("5m", "15m"):
        sub = df[df["tf"] == tf]
        n = len(sub)
        if n == 0:
            continue
        buggy_fires = (sub["first_trigger_buggy"] >= 0).sum()
        strict_fires = (sub["first_trigger_strict"] >= 0).sum()
        # % triggered ONLY under buggy (lookahead "phantom" triggers)
        only_buggy = ((sub["first_trigger_buggy"] >= 0) & (sub["first_trigger_strict"] < 0)).sum()
        # delta first-trigger bucket
        with_both = sub.dropna(subset=["delta_first"])
        avg_delta = with_both["delta_first"].mean() if len(with_both) else 0
        print(
            f"  {tf}: n={n:3d}  buggy_fires={buggy_fires}/{n} ({buggy_fires/n*100:.0f}%)  "
            f"strict_fires={strict_fires}/{n} ({strict_fires/n*100:.0f}%)  "
            f"phantom={only_buggy}  avg_first_bucket_delta={avg_delta:.1f} "
            f"({avg_delta * 10:.0f}s later under strict)"
        )

    # Late-trigger analysis: triggers in last 50s (buckets 25-29 for 5m)
    print("\n[5] 5m late-trigger analysis (buckets 25-29 = last 50s = lookahead zone):")
    sub5 = df[df["tf"] == "5m"]
    late_buggy = sub5[(sub5["first_trigger_buggy"] >= 25)]
    print(f"  total 5m matched: {len(sub5)}")
    print(f"  5m with first-trigger in BUCKET 25-29 (last 50s) under buggy: {len(late_buggy)}")
    print(f"  these are the trades where lookahead gives a 'free' hedge close to resolution")
    print(f"  under strict: how many of those still trigger?")
    survived = late_buggy[late_buggy["first_trigger_strict"] >= 0]
    print(f"  survive strict (still trigger somewhere): {len(survived)} of {len(late_buggy)}")
    if len(late_buggy) > 0:
        # Of those surviving, what's their new first-trigger bucket?
        if len(survived) > 0:
            print(f"  if survived, mean strict first-trigger bucket: {survived['first_trigger_strict'].mean():.1f}")

    # 5m HEDGE/SELL window length
    print("\n[6] 5m monitoring window structure:")
    print("  Buckets 13-29 = 17 buckets = 170 seconds")
    print("  Buckets 13-24 (those NOT touching last-bar lookahead) = 12 buckets = 120 seconds")
    print("  Effective monitoring window after fix = 120s instead of 170s = 30% shorter")

    return df


if __name__ == "__main__":
    main()
