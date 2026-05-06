"""backtest_vs_shadow_audit.py — compare phase7_validation_v3_full backtest vs live shadow.

For each market that PRODUCTION fired on (from trading.events), check:
  - Did my backtest also fire on the same slug?
  - Same direction (Up/Down)?
  - Same outcome?
  - Same ret_5m sign?

Diagnoses whether differences in hit-rate come from:
  - Different ret_5m source (HL perp vs Binance spot)
  - Different threshold fitting
  - Bug in backtest

Inputs:
  data/v4/shadow_trades_2026_05_02/vps3_v3_family_full.csv  (production fires)
  data/v4/refresh_2026_05_02/{asset}_markets_minimal.csv     (outcomes)
  data/v4/refresh_2026_05_02/{asset}_book_depth_v3_full.csv  (orderbook bucket 0)
  data/v4/refresh_2026_05_02/hl_klines_full.csv              (HL klines for our ret_5m)
"""
from __future__ import annotations
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT / "data" / "v4" / "refresh_2026_05_02"
SHADOW = ROOT / "data" / "v4" / "shadow_trades_2026_05_02" / "vps3_v3_family_full.csv"

sys.path.insert(0, str(ROOT / "strategy_lab" / "v4_signals"))
from phase7_validation_v3_full import (
    load_klines, load_markets_minimal, load_book_depth_bucket0,
    compute_returns, multi_horizon_aligned, V3_REQUIRE_MULTI_HORIZON
)


def load_shadow_trades() -> list[dict]:
    """Production events lack slug/window_start_unix in payload; derive window_start from `at` timestamp.

    Resolution events log just after window_end. window_start = floor(at_unix / 300) * 300 - 300.
    """
    rows = []
    with open(SHADOW, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                # Parse timestamp like "2026-04-30 07:46:00.692075+02"
                from datetime import datetime
                at = datetime.fromisoformat(r["at"].replace(" ", "T"))
                at_unix = int(at.timestamp())
                # Resolution event ~at window_end. Snap to 5min boundary (rounding DOWN), subtract 300 → window_start.
                # If event is within 0-300s of a 5min boundary, that boundary IS window_end.
                window_end_unix = (at_unix // 300) * 300
                # If at_unix falls EXACTLY on a 5min boundary the event is for the previous window.
                # Otherwise it's for the window ending at the nearest 5min boundary <= at_unix.
                if at_unix > window_end_unix:
                    pass  # window_end is the floor → window_start is window_end - 300
                else:
                    # at_unix is exactly on boundary — event was for a 5min window ending here? Edge case; same logic.
                    pass
                r["window_start_unix"] = window_end_unix - 300
                r["won_bool"] = r.get("won") in ("t", "true", "True", "1")
                r["pnl_usd_f"] = float(r.get("pnl_usd") or 0)
            except (ValueError, TypeError, KeyError):
                continue
            rows.append(r)
    return rows


def main() -> int:
    print("=== Shadow vs Backtest Audit ===")
    klines_map = load_klines()
    print(f"  klines loaded: {sum(len(v) for v in klines_map.values())} bars")

    # Load all 3 assets' markets + books
    markets_all = {}
    books_all = {}
    for asset in ("btc", "eth", "sol"):
        for slug, mk in load_markets_minimal(asset).items():
            markets_all[slug] = mk
        for slug, book in load_book_depth_bucket0(asset).items():
            books_all[slug] = book
    print(f"  markets indexed: {len(markets_all)}")
    print(f"  books indexed:   {len(books_all)}")

    shadow = load_shadow_trades()
    print(f"  shadow trades:   {len(shadow)}")

    # Per-sleeve hit rate from shadow (production)
    by_sleeve_prod = defaultdict(list)
    for s in shadow:
        sleeve = s["sleeve_id"]
        by_sleeve_prod[sleeve].append(s)

    print("\n=== Production (shadow) hit rates per sleeve ===")
    print(f"  {'sleeve':30s}  {'n':>3s}  {'hit%':>5s}  {'pnl$':>8s}")
    for sleeve in sorted(by_sleeve_prod):
        trades = by_sleeve_prod[sleeve]
        wins = sum(1 for t in trades if t["won_bool"])
        pnl = sum(t["pnl_usd_f"] for t in trades)
        hr = wins / len(trades) * 100 if trades else 0
        print(f"  {sleeve:30s}  {len(trades):>3d}  {hr:>4.1f}%  {pnl:>+8.2f}")

    # Build markets index by (asset, window_start_unix) for matching
    markets_by_ws: dict[tuple[str, int], dict] = {}
    for slug, mk in markets_all.items():
        markets_by_ws[(mk["asset"], mk["window_start_unix"])] = mk
    print(f"  markets_by_ws indexed: {len(markets_by_ws)}")

    # Now per-trade audit: match by (symbol, window_start_unix derived from `at`)
    print("\n=== TRADE-LEVEL AUDIT ===")
    matches = defaultdict(lambda: defaultdict(int))  # sleeve → field → count

    for s in shadow:
        sleeve = s["sleeve_id"]
        symbol = (s.get("symbol") or "").upper()
        ws = s["window_start_unix"]
        mk = markets_by_ws.get((symbol, ws))
        if not mk:
            matches[sleeve]["no_market_match"] += 1
            continue

        # Outcome check: do our outcome_up and shadow's "won" + "signal" agree?
        # Shadow signal=Up + won=True → outcome_up=1. signal=Down + won=True → outcome_up=0.
        prod_signal = (s.get("signal") or "").upper()
        prod_won = s["won_bool"]
        if prod_signal == "UP":
            implied_outcome_up = 1 if prod_won else 0
        elif prod_signal == "DOWN":
            implied_outcome_up = 0 if prod_won else 1
        else:
            matches[sleeve]["unknown_signal"] += 1
            continue

        if implied_outcome_up == mk["outcome_up"]:
            matches[sleeve]["outcome_match"] += 1
        else:
            matches[sleeve]["outcome_MISMATCH"] += 1
            if matches[sleeve]["outcome_MISMATCH"] <= 3:
                print(f"    [outcome mismatch] {sleeve} {slug}: shadow signal={prod_signal} won={prod_won} → implied outcome_up={implied_outcome_up}; our outcome_up={mk['outcome_up']}")

        # Direction check: does our ret_5m sign match production's signal?
        asset = mk["asset"].lower()
        ret_ours = compute_returns(klines_map, asset, mk["window_start_unix"])
        if not math.isfinite(ret_ours["ret_5m"]):
            matches[sleeve]["our_ret_5m_nan"] += 1
            continue

        our_dir = "UP" if ret_ours["ret_5m"] > 0 else "DOWN"
        if our_dir == prod_signal:
            matches[sleeve]["direction_match"] += 1
        else:
            matches[sleeve]["direction_MISMATCH"] += 1

    print(f"\n  Per-sleeve audit summary:")
    for sleeve, m in sorted(matches.items()):
        n = sum(m.values())
        # Build cell summary
        kv = ", ".join(f"{k}={v}" for k, v in sorted(m.items()))
        print(f"    {sleeve} (events seen: {n}):")
        print(f"      {kv}")

    # The key comparison: replicate decision on PRODUCTION-FIRED slugs in our backtest
    print("\n=== Production-fired markets — replicate decision in backtest (using HL klines) ===")
    print(f"  {'sleeve':30s}  {'prod_n':>6s}  {'matched':>7s}  {'shadow_hit':>10s}  {'our_dir_match%':>14s}  {'our_replic_hit':>14s}")
    for sleeve in sorted(by_sleeve_prod):
        require_mh_for_eval = False  # for replication-on-same-slug we don't filter by MH
        trades = by_sleeve_prod[sleeve]
        n_match = 0
        n_dir_match = 0
        replic_wins = 0
        prod_wins = 0
        prod_n = 0
        for t in trades:
            symbol = (t.get("symbol") or "").upper()
            ws = t["window_start_unix"]
            mk = markets_by_ws.get((symbol, ws))
            if not mk:
                continue
            n_match += 1
            asset = mk["asset"].lower()
            ret = compute_returns(klines_map, asset, mk["window_start_unix"])
            if not math.isfinite(ret["ret_5m"]) or ret["ret_5m"] == 0:
                continue
            our_dir = "UP" if ret["ret_5m"] > 0 else "DOWN"
            prod_dir = (t.get("signal") or "").upper()
            if our_dir == prod_dir:
                n_dir_match += 1
            # Did our predicted direction win?
            our_won = (our_dir == "UP" and mk["outcome_up"] == 1) or (our_dir == "DOWN" and mk["outcome_up"] == 0)
            if our_won:
                replic_wins += 1
            prod_n += 1
            if t["won_bool"]:
                prod_wins += 1
        if prod_n == 0:
            continue
        prod_hit = prod_wins / prod_n * 100
        our_replic_hit = replic_wins / prod_n * 100
        dir_match_pct = n_dir_match / prod_n * 100
        print(f"  {sleeve:30s}  {prod_n:>6d}  {n_match:>7d}  {prod_hit:>9.1f}%  {dir_match_pct:>13.1f}%  {our_replic_hit:>13.1f}%")

    print("\n  Interpretation:")
    print("    - shadow_hit = production hit rate (truth)")
    print("    - our_dir_match% = % of trades where our HL-derived ret_5m sign matches production's signal")
    print("      (low = HL perp differs from production's Binance spot ret_5m direction)")
    print("    - our_replic_hit = if we used OUR direction (HL-derived) on the same markets, hit rate")
    print("      (compare to shadow_hit: difference reveals divergence between HL and Binance)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
