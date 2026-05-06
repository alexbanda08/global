"""match_shadow_strict — same as match_shadow.py but uses asof_strict.

Tests whether the 5m profitability seen in the backtest survives when we use
end-time-indexed klines (no lookahead) instead of start-time-indexed (which
leaks 0-60s of future price into the rev_bp computation).
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

# Reuse most of match_shadow but with strict asof
from strategy_lab.momo_realfill import match_shadow as ms
from strategy_lab.momo_realfill.verify_lookahead_bug import asof_strict
from book_walk import book_walk_fill                    # noqa: E402
from extended_backtest_with_robustness import (         # noqa: E402
    NOTIONAL_USD, FEE_RATE, SPREAD_FILTER, sell_at_bid, load_klines,
)
from loaders.raw_orderbook_l25 import OrderbookIndex, load_orderbook_l25_raw  # noqa: E402

REV_BP = 5
LEVELS = 25
_OID = {"Up": 0, "Down": 1}


def simulate_strict(row, klines, indices):
    """Mirror simulate_one but uses asof_strict for kline lookups."""
    asset = row["asset"]
    tf = row["timeframe"]
    policy = row["exit"]
    sig_str = row["signal"]
    held = "Up" if sig_str == "UP" else "Down"
    other = "Down" if sig_str == "UP" else "Up"
    held_id = _OID[held]
    other_id = _OID[other]

    ob_idx = indices[asset.lower()]
    k1m = klines[asset.lower()]
    ws_s = int(row["ws_unix"])
    entry_ts_us = (ws_s + 120) * 1_000_000

    asks_p, asks_s = ob_idx.book_at(row["slug"], held_id, entry_ts_us, side="ask")
    if asks_p is None:
        return {"matched": False, "reason": "no_book_at_entry"}

    spread_thr = SPREAD_FILTER[asset.lower()]
    bids_p, _ = ob_idx.book_at(row["slug"], held_id, entry_ts_us, side="bid")
    if (asks_p[0] is not None and bids_p is not None and bids_p[0] is not None
            and np.isfinite(asks_p[0]) and np.isfinite(bids_p[0])
            and (asks_p[0] - bids_p[0]) > spread_thr):
        return {"matched": False, "reason": "spread_filter_skip"}

    vwap_e, shares_e, usd_e, _, under_e = book_walk_fill(asks_p, asks_s, NOTIONAL_USD)
    if shares_e <= 0:
        return {"matched": False, "reason": "thin_book"}
    if under_e and usd_e < NOTIONAL_USD * 0.5:
        return {"matched": False, "reason": "thin_book_skip"}

    # ★ STRICT asof for entry reference
    asset_at_entry = asof_strict(k1m, ws_s + 120)
    if not (asset_at_entry and np.isfinite(asset_at_entry)):
        return {"matched": False, "reason": "no_strict_kline_at_entry"}

    sig = 1 if sig_str == "UP" else 0
    max_b = 89 if tf == "15m" else 29

    exit_event = None
    if policy != "HOLD":
        for bucket in range(13, max_b + 1):
            ts_in_s = ws_s + bucket * 10
            ts_in_us = ts_in_s * 1_000_000
            # ★ STRICT asof for monitoring
            a_now = asof_strict(k1m, ts_in_s)
            if not np.isfinite(a_now):
                continue
            bp_rev = (a_now - asset_at_entry) / asset_at_entry * 10000.0
            trig = (sig == 1 and bp_rev <= -REV_BP) or (sig == 0 and bp_rev >= REV_BP)
            if not trig:
                continue
            if policy == "HEDGE":
                h_ask_p, h_ask_s = ob_idx.book_at(row["slug"], other_id, ts_in_us, side="ask")
                if h_ask_p is None or len(h_ask_p) == 0 or h_ask_p[0] is None or not np.isfinite(h_ask_p[0]):
                    continue
                top = float(h_ask_p[0])
                if not (0 < top < 1):
                    continue
                target = shares_e * top
                vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, target)
                if shares_h > 0:
                    if shares_h < shares_e * 0.95 and not under_h:
                        vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(
                            h_ask_p, h_ask_s, shares_e * vwap_h
                        )
                    exit_event = ("hedge", bucket, dict(vwap_h=vwap_h, shares_h=shares_h, usd_h=usd_h))
                    break
            elif policy == "SELL":
                b_p, b_s = ob_idx.book_at(row["slug"], held_id, ts_in_us, side="bid")
                if b_p is None:
                    continue
                sv, sg = sell_at_bid(np.asarray(b_p), np.asarray(b_s), shares_e)
                if np.isfinite(sv) and sg > 0:
                    exit_event = ("sell", bucket, dict(sell_vwap=sv, sell_gross=sg))
                    break

    won = bool(row["won"])
    if exit_event is None:
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE_RATE if profit > 0 else 0.0
            pnl_rf = profit - fee
        else:
            pnl_rf = -usd_e
        exit_reason = "hold"
    else:
        kind, _, ed = exit_event
        if kind == "hedge":
            cost = usd_e + ed["usd_h"]
            if won:
                gross = shares_e * 1.0
                fee = shares_e * (1.0 - vwap_e) * FEE_RATE
            else:
                gross = ed["shares_h"] * 1.0
                fee = ed["shares_h"] * (1.0 - ed["vwap_h"]) * FEE_RATE
            pnl_rf = gross - cost - fee
            exit_reason = "hedge"
        else:
            profit = ed["sell_gross"] - usd_e
            fee = max(profit, 0) * FEE_RATE
            pnl_rf = profit - fee
            exit_reason = "sell"

    return {"matched": True, "rf_vwap_e": vwap_e, "rf_pnl": pnl_rf, "rf_exit": exit_reason}


def main():
    print("[1] loading shadow…")
    shadow = ms.load_shadow()
    print(f"    {len(shadow)} fires; {shadow['slug'].nunique()} unique slugs")

    print("[2] loading klines + L25 indices…")
    klines = load_klines()
    indices = {}
    for asset in ("btc", "eth", "sol"):
        slugs = set(shadow[shadow.asset == asset.upper()]["slug"].unique())
        if not slugs:
            continue
        ob_df = load_orderbook_l25_raw(asset, slugs=slugs)
        indices[asset] = OrderbookIndex(ob_df)
        print(f"    [{asset}] {len(slugs)} slugs → {len(ob_df):,} L25 rows indexed")

    print("[3] simulating each shadow fire with STRICT asof (no lookahead)…")
    results = []
    n_match = n_skip = 0
    for _, row in shadow.iterrows():
        if row["asset"].lower() not in indices:
            continue
        sim = simulate_strict(row, klines, indices)
        if sim.get("matched"):
            n_match += 1
        else:
            n_skip += 1
        results.append({**row.to_dict(), **sim})
    print(f"    matched={n_match}, skipped={n_skip}")

    df = pd.DataFrame(results)
    matched_df = df[df["matched"] == True].copy()  # noqa: E712
    matched_df["pnl_diff_strict_vs_shadow"] = matched_df["rf_pnl"] - matched_df["pnl_usd"]

    print("\n[4] STRICT realfill vs shadow per cell:\n")
    grp = matched_df.groupby(["asset", "timeframe", "exit"])
    rows = []
    for (a, tf, ex), g in grp:
        rows.append({
            "cell": f"{a}_{tf}_{ex}",
            "n": len(g),
            "shadow_$/trade": float(g["pnl_usd"].mean()),
            "rf_strict_$/trade": float(g["rf_pnl"].mean()),
            "delta_per_trade": float(g["pnl_diff_strict_vs_shadow"].mean()),
            "rf_hedge_count": int((g["rf_exit"] == "hedge").sum()),
            "rf_sell_count": int((g["rf_exit"] == "sell").sum()),
            "rf_hold_count": int((g["rf_exit"] == "hold").sum()),
        })
    summary = pd.DataFrame(rows)
    print(summary.to_string(index=False, float_format=lambda x: f"{x:+.3f}"))

    out = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_shadow_match_strict.csv"
    summary.to_csv(out, index=False)
    print(f"\n[csv] → {out}")

    # Compare vs buggy realfill
    buggy_summary = pd.read_csv(
        ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_shadow_match_summary.csv"
    )
    print("\n[5] STRICT vs BUGGY realfill per cell ($/trade):\n")
    print(f"{'cell':<22} {'n':>4} {'buggy':>10} {'strict':>10} {'delta':>10}")
    for _, r in summary.iterrows():
        bm = buggy_summary[buggy_summary["cell"] == r["cell"]]
        if len(bm) == 0:
            continue
        bm_val = float(bm["rf_pnl_mean"].iloc[0])
        s_val = r["rf_strict_$/trade"]
        print(f"{r['cell']:<22} {int(r['n']):>4} {bm_val:>+10.3f} {s_val:>+10.3f} {s_val - bm_val:>+10.3f}")


if __name__ == "__main__":
    main()
