"""
stoploss_backtest — does adding a stop-loss exit improve V3 ∪ Phase 7 union strategy?

Asymmetric Polymarket payoff:
  Win:  bet 0.50, payoff 1.00, fee 0.005 → +0.495 net
  Loss: bet 0.50, payoff 0.00, fee 0.005 → -0.505 net (102% loss on capital)

Hypothesis: cutting losses early (stop-loss exit at bid > 0) reduces the 102%
loss on losing bets, even at the cost of stopping out some bets that would
have eventually won (false stops on noise).

Method:
  - For each of 534 union bets, walk the YES (Up bet) or NO (Down bet) token
    bid price across the in-market 10s buckets.
  - At each bucket, check if best bid for our token has dropped below `stop`.
  - If yes: exit at that bid (sell into the book), book the small loss.
  - If no: hold to resolution; payoff is 1.00 (win) or 0.00 (loss).
  - Compute total PnL across all 534 bets at each stop threshold.

Outputs:
  strategy_lab/results/meta_classifier/stoploss_results.csv
  strategy_lab/reports/STOPLOSS_BACKTEST.md
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
UNION = ROOT / "strategy_lab" / "results" / "meta_classifier" / "combined_v3_phase7.csv"
BOOK = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_book_depth_v3_full.csv"
OUT = ROOT / "strategy_lab" / "results" / "meta_classifier" / "stoploss_results.csv"

ENTRY_PX = 0.50
FEE_PER_SIDE = 0.005  # 1c round-trip total

STOP_LEVELS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, None]


def load_union_bets():
    df = pd.read_csv(UNION)
    fired = df[(df["v3_fired"] | df["p7_fired"]) & df["outcome_up"].notna()].copy()
    # union_direction: 1=UP (bought YES/Up token), 0=DOWN (bought NO/Down token)
    fired = fired.dropna(subset=["union_direction"])
    fired["union_direction"] = fired["union_direction"].astype(int)
    fired["token_we_bought"] = fired["union_direction"].map({1: "Up", 0: "Down"})
    print(f"loaded {len(fired)} union bets")
    print(f"  bought Up token: {(fired['union_direction']==1).sum()}")
    print(f"  bought Down token: {(fired['union_direction']==0).sum()}")
    return fired


def load_book_for_slugs(slugs: set, tokens_per_slug: dict):
    """Stream book_depth filtering to (slug, token) we care about. Return dict
    slug -> list of (bucket_10s, best_bid) sorted by bucket."""
    print(f"streaming {BOOK.name} (~150MB)...")
    book = {}  # slug -> list of (bucket, bid)
    chunks = pd.read_csv(BOOK, usecols=["slug", "outcome", "bucket_10s", "bid_price_0"], chunksize=100_000)
    n_rows = 0
    for chunk in chunks:
        n_rows += len(chunk)
        # Filter to our slugs
        m = chunk["slug"].isin(slugs)
        if not m.any():
            continue
        sub = chunk[m]
        # Filter to OUR token per slug
        for _, row in sub.iterrows():
            slug = row["slug"]
            want_token = tokens_per_slug.get(slug)
            if row["outcome"] != want_token:
                continue
            book.setdefault(slug, []).append((int(row["bucket_10s"]), float(row["bid_price_0"])))
    # Sort by bucket
    for slug in book:
        book[slug].sort()
    print(f"  scanned {n_rows:,} rows, retained book history for {len(book)} slugs")
    return book


def simulate_bet(slug: str, direction: int, outcome_up: int, book_entries: list, stop: float | None) -> dict:
    """Simulate one bet with optional stop-loss.
    Returns dict with stopped_out, exit_bid, pnl."""
    # Determine if WE won (regardless of stop)
    won = (direction == 1 and outcome_up == 1) or (direction == 0 and outcome_up == 0)
    # Walk buckets in order — find first stop trigger
    if stop is not None and book_entries:
        for bucket, bid in book_entries:
            if bid < stop:
                # Stop out at this bid
                pnl = bid - ENTRY_PX - 2 * FEE_PER_SIDE  # entry + exit fees
                return {"stopped_out": True, "exit_bid": bid, "exit_bucket": bucket,
                        "pnl": pnl, "would_have_won": won}
    # No stop or never triggered — hold to resolution
    payoff = 1.00 if won else 0.00
    pnl = payoff - ENTRY_PX - FEE_PER_SIDE  # only entry fee on resolution
    return {"stopped_out": False, "exit_bid": payoff, "exit_bucket": None,
            "pnl": pnl, "would_have_won": won}


def main():
    fired = load_union_bets()
    slugs = set(fired["slug"])
    tokens = dict(zip(fired["slug"], fired["token_we_bought"]))

    book = load_book_for_slugs(slugs, tokens)
    in_book = fired["slug"].isin(book.keys())
    print(f"\nbets matched to book: {in_book.sum()}/{len(fired)}")
    fired = fired[in_book].reset_index(drop=True)

    # For each stop level, simulate every bet
    rows = []
    for stop in STOP_LEVELS:
        stop_label = f"{stop:.2f}" if stop is not None else "none"
        per_bet = []
        for _, b in fired.iterrows():
            r = simulate_bet(b["slug"], int(b["union_direction"]), int(b["outcome_up"]),
                             book.get(b["slug"], []), stop)
            per_bet.append(r)
        df = pd.DataFrame(per_bet)
        df["bet_slug"] = fired["slug"].values
        df["timeframe"] = fired["timeframe"].values
        df["direction"] = fired["union_direction"].values

        n = len(df)
        n_stopped = df["stopped_out"].sum()
        n_resolved = (~df["stopped_out"]).sum()
        wins_at_resolution = ((~df["stopped_out"]) & df["would_have_won"]).sum()
        false_stops = (df["stopped_out"] & df["would_have_won"]).sum()  # bets that would have won
        true_stops = (df["stopped_out"] & ~df["would_have_won"]).sum()  # bets that would have lost
        total_pnl = df["pnl"].sum()
        avg_pnl = df["pnl"].mean()
        roi = avg_pnl / ENTRY_PX  # ROI on capital risked
        avg_loss_when_stopped = df.loc[df["stopped_out"], "pnl"].mean() if n_stopped else 0
        avg_loss_when_resolution_loss = df.loc[(~df["stopped_out"]) & ~df["would_have_won"], "pnl"].mean() if n_resolved > 0 else 0

        rows.append({
            "stop_level": stop_label,
            "n_bets": n,
            "n_stopped": int(n_stopped),
            "n_resolved": int(n_resolved),
            "wins_at_resolution": int(wins_at_resolution),
            "true_stops_saved": int(true_stops),
            "false_stops_lost": int(false_stops),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_per_bet": round(avg_pnl, 4),
            "roi_per_bet_pct": round(roi * 100, 2),
            "avg_loss_when_stopped": round(avg_loss_when_stopped, 4),
            "avg_loss_full_resolution_loss": round(avg_loss_when_resolution_loss, 4),
        })
        print(f"  stop={stop_label:>4}: n={n} stopped={n_stopped:>3} (true={true_stops}/false={false_stops})  "
              f"resolved={n_resolved} wins={wins_at_resolution}  total_pnl=${total_pnl:+.2f}  ROI={roi*100:+.2f}%")

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"\nWrote {OUT}")
    print()
    print("=== SUMMARY TABLE ===")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
