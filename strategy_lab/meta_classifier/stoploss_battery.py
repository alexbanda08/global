"""
stoploss_battery — comprehensive stop-loss rule sweep on V3 ∪ Phase 7 union.

Tests 22+ stop rules across 5 categories to find any rule that beats no-stop:
  A. Floor protection      (only catch catastrophic drops)
  B. Time-windowed level   (stop only in late window)
  C. Velocity stops        (stop on sharp drops in N buckets)
  D. Velocity + early skip (skip first N seconds of noise)
  E. Hybrid combos         (floor OR velocity, etc.)

For each rule + bet:
  - Walk book history bucket-by-bucket
  - Check stop trigger
  - If triggered: exit at that bid; PnL = bid - 0.50 - 2×fee
  - If not: hold to resolution; PnL = 1.00/0 - 0.50 - fee

Outputs:
  strategy_lab/results/meta_classifier/stoploss_battery_results.csv
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
UNION = ROOT / "strategy_lab" / "results" / "meta_classifier" / "combined_v3_phase7.csv"
BOOK = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_book_depth_v3_full.csv"
OUT = ROOT / "strategy_lab" / "results" / "meta_classifier" / "stoploss_battery_results.csv"

ENTRY_PX = 0.50
FEE_PER_SIDE = 0.005


def load_union_bets():
    df = pd.read_csv(UNION)
    fired = df[(df["v3_fired"] | df["p7_fired"]) & df["outcome_up"].notna()].copy()
    fired = fired.dropna(subset=["union_direction"])
    fired["union_direction"] = fired["union_direction"].astype(int)
    fired["token_we_bought"] = fired["union_direction"].map({1: "Up", 0: "Down"})
    return fired


def load_book_for_slugs(slugs: set, tokens_per_slug: dict):
    """Stream book_depth → dict slug -> sorted list of (bucket, bid)."""
    book = {}
    chunks = pd.read_csv(BOOK,
                          usecols=["slug", "outcome", "bucket_10s", "bid_price_0", "timeframe"],
                          chunksize=100_000)
    for chunk in chunks:
        m = chunk["slug"].isin(slugs)
        if not m.any():
            continue
        sub = chunk[m]
        for _, row in sub.iterrows():
            slug = row["slug"]
            if row["outcome"] != tokens_per_slug.get(slug):
                continue
            book.setdefault(slug, []).append((int(row["bucket_10s"]), float(row["bid_price_0"])))
    for slug in book:
        book[slug].sort()
    return book


def get_max_bucket(timeframe: str) -> int:
    """5m=30 buckets (0-29), 15m=90 buckets."""
    return 90 if timeframe == "15m" else 30


# ─── stop rule definitions ─────────────────────────────────────────────────
# Each rule: takes (book_entries, max_bucket, current_idx, current_bid) and returns bool
# But simpler: each rule is a function(book_entries, max_bucket) -> (should_stop, exit_bucket, exit_bid)

def rule_no_stop(book_entries, max_bucket):
    return None  # never trigger


def make_floor_rule(floor: float):
    def rule(book_entries, max_bucket):
        for bucket, bid in book_entries:
            if bid < floor:
                return (bucket, bid)
        return None
    return rule


def make_window_level_rule(level: float, last_n_buckets: int):
    """Stop if bid < level AND bucket >= max_bucket - last_n_buckets."""
    def rule(book_entries, max_bucket):
        gate_bucket = max_bucket - last_n_buckets
        for bucket, bid in book_entries:
            if bucket >= gate_bucket and bid < level:
                return (bucket, bid)
        return None
    return rule


def make_velocity_rule(drop: float, window_buckets: int = 1):
    """Stop if bid drops >= drop within last window_buckets buckets (vs trailing max)."""
    def rule(book_entries, max_bucket):
        # Build prev-bid lookup
        for i, (bucket, bid) in enumerate(book_entries):
            # Look at trailing window
            start_idx = max(0, i - window_buckets)
            window_bids = [b for _, b in book_entries[start_idx:i+1]]
            if not window_bids:
                continue
            max_in_window = max(window_bids)
            if max_in_window - bid >= drop:
                return (bucket, bid)
        return None
    return rule


def make_velocity_skip_rule(drop: float, window_buckets: int, skip_first_n_buckets: int):
    """Velocity rule but ignore first N buckets (skip early noise)."""
    def rule(book_entries, max_bucket):
        for i, (bucket, bid) in enumerate(book_entries):
            if bucket < skip_first_n_buckets:
                continue
            start_idx = max(0, i - window_buckets)
            window_bids = [b for _, b in book_entries[start_idx:i+1]]
            if not window_bids:
                continue
            max_in_window = max(window_bids)
            if max_in_window - bid >= drop:
                return (bucket, bid)
        return None
    return rule


def make_hybrid_floor_velocity(floor: float, drop: float, window_buckets: int = 1):
    """Stop if EITHER bid < floor (catastrophic) OR rapid drop >= drop in window_buckets."""
    floor_rule = make_floor_rule(floor)
    vel_rule = make_velocity_rule(drop, window_buckets)
    def rule(book_entries, max_bucket):
        # Walk buckets, check both conditions, take whichever triggers FIRST
        for i, (bucket, bid) in enumerate(book_entries):
            if bid < floor:
                return (bucket, bid)
            start_idx = max(0, i - window_buckets)
            window_bids = [b for _, b in book_entries[start_idx:i+1]]
            if window_bids and (max(window_bids) - bid) >= drop:
                return (bucket, bid)
        return None
    return rule


def make_hybrid_floor_late_level(floor: float, late_level: float, last_n_buckets: int):
    """Stop if EITHER bid < floor OR (bid < late_level AND in last N buckets)."""
    def rule(book_entries, max_bucket):
        gate_bucket = max_bucket - last_n_buckets
        for bucket, bid in book_entries:
            if bid < floor:
                return (bucket, bid)
            if bucket >= gate_bucket and bid < late_level:
                return (bucket, bid)
        return None
    return rule


# ─── rule registry ─────────────────────────────────────────────────────────
RULES = {
    "no_stop": rule_no_stop,
    # A. Floor protection
    "A1_floor_0.05": make_floor_rule(0.05),
    "A2_floor_0.10": make_floor_rule(0.10),
    "A3_floor_0.15": make_floor_rule(0.15),
    "A4_floor_0.20": make_floor_rule(0.20),
    # B. Time-windowed level (last 60s / 90s / 120s)
    "B1_lvl0.30_last_60s": make_window_level_rule(0.30, 6),
    "B2_lvl0.30_last_90s": make_window_level_rule(0.30, 9),
    "B3_lvl0.30_last_120s": make_window_level_rule(0.30, 12),
    "B4_lvl0.20_last_60s": make_window_level_rule(0.20, 6),
    "B5_lvl0.20_last_90s": make_window_level_rule(0.20, 9),
    "B6_lvl0.20_last_120s": make_window_level_rule(0.20, 12),
    "B7_lvl0.40_last_60s": make_window_level_rule(0.40, 6),
    "B8_lvl0.40_last_90s": make_window_level_rule(0.40, 9),
    # C. Velocity (drop in 1, 2, 3 buckets)
    "C1_vel0.20_1bkt": make_velocity_rule(0.20, 1),
    "C2_vel0.30_1bkt": make_velocity_rule(0.30, 1),
    "C3_vel0.40_1bkt": make_velocity_rule(0.40, 1),
    "C4_vel0.20_3bkt": make_velocity_rule(0.20, 3),
    "C5_vel0.30_3bkt": make_velocity_rule(0.30, 3),
    # D. Velocity + skip early
    "D1_vel0.20_1bkt_skip30s": make_velocity_skip_rule(0.20, 1, 3),
    "D2_vel0.30_1bkt_skip30s": make_velocity_skip_rule(0.30, 1, 3),
    "D3_vel0.30_1bkt_skip60s": make_velocity_skip_rule(0.30, 1, 6),
    # E. Hybrid floor + velocity / late-level
    "E1_floor0.10+vel0.30_1bkt": make_hybrid_floor_velocity(0.10, 0.30, 1),
    "E2_floor0.10+late0.30_60s": make_hybrid_floor_late_level(0.10, 0.30, 6),
    "E3_floor0.10+late0.20_60s": make_hybrid_floor_late_level(0.10, 0.20, 6),
    "E4_floor0.05+vel0.40_1bkt": make_hybrid_floor_velocity(0.05, 0.40, 1),
}


def simulate_bet_with_rule(bet, book_entries, max_bucket, rule_fn) -> dict:
    """Apply one rule to one bet. Return PnL + diagnostic."""
    direction = int(bet["union_direction"])
    outcome_up = int(bet["outcome_up"])
    won = (direction == 1 and outcome_up == 1) or (direction == 0 and outcome_up == 0)

    triggered = rule_fn(book_entries, max_bucket)
    if triggered is not None:
        bucket, bid = triggered
        pnl = bid - ENTRY_PX - 2 * FEE_PER_SIDE
        return {"stopped": True, "exit_bucket": bucket, "exit_bid": bid,
                "pnl": pnl, "would_have_won": won}

    payoff = 1.00 if won else 0.00
    pnl = payoff - ENTRY_PX - FEE_PER_SIDE
    return {"stopped": False, "exit_bucket": None, "exit_bid": payoff,
            "pnl": pnl, "would_have_won": won}


def main():
    print("=== loading union bets ===")
    fired = load_union_bets()
    print(f"  {len(fired)} bets fired (V3 OR P7)")

    slugs = set(fired["slug"])
    tokens = dict(zip(fired["slug"], fired["token_we_bought"]))

    print("=== loading book history (streaming 150MB) ===")
    book = load_book_for_slugs(slugs, tokens)
    in_book = fired["slug"].isin(book.keys())
    fired = fired[in_book].reset_index(drop=True)
    print(f"  {len(fired)} bets matched to book")

    print(f"\n=== running {len(RULES)} stop rules × {len(fired)} bets ===\n")
    rows = []
    for rule_name, rule_fn in RULES.items():
        per_bet = []
        for _, bet in fired.iterrows():
            book_entries = book[bet["slug"]]
            max_bucket = get_max_bucket(bet["timeframe"])
            per_bet.append(simulate_bet_with_rule(bet, book_entries, max_bucket, rule_fn))

        df = pd.DataFrame(per_bet)
        n = len(df)
        n_stopped = int(df["stopped"].sum())
        n_resolved = n - n_stopped
        wins_at_resolution = int(((~df["stopped"]) & df["would_have_won"]).sum())
        true_stops = int((df["stopped"] & ~df["would_have_won"]).sum())
        false_stops = int((df["stopped"] & df["would_have_won"]).sum())
        total_pnl = float(df["pnl"].sum())
        roi = float(df["pnl"].mean()) / ENTRY_PX

        # Extra diagnostics
        true_pos_rate = true_stops / max(n_stopped, 1)  # precision of stop
        winners_kept = wins_at_resolution / max(int(df["would_have_won"].sum()), 1)  # recall of winners

        rows.append({
            "rule": rule_name,
            "n_bets": n,
            "n_stopped": n_stopped,
            "true_stops": true_stops,
            "false_stops": false_stops,
            "n_resolved": n_resolved,
            "wins_at_resolution": wins_at_resolution,
            "stop_precision": round(true_pos_rate, 3),
            "winners_kept": round(winners_kept, 3),
            "total_pnl": round(total_pnl, 2),
            "roi_per_bet": round(roi * 100, 2),
        })

    out = pd.DataFrame(rows).sort_values("total_pnl", ascending=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"Wrote {OUT}\n")

    print("=== ALL RULES (sorted by total PnL) ===")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
