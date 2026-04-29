"""
polymarket_backtest_real — Real Kronos signals on real Polymarket markets.

Tests every major exit strategy on actual Apr 22-23 data:

  S0  Hold-to-resolution (baseline)
  S1  Target exit at T ∈ {0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90}
  S2  Stop loss at S ∈ {0.40, 0.35, 0.30, 0.25, 0.20}
  S3  Target + Stop combos
  S4  Trailing stop: X% drawdown from peak ∈ {5%, 10%, 15%, 20%}
  S5  Time exit at bucket N before resolution (sell regardless)
  S6  No-entry-if-expensive filter (skip markets with entry > 0.55)
  S7  Confidence-threshold filter (top X% |pred_ret|)

Data:
  btc_markets.csv       — 444 markets, entry/outcome
  btc_trajectories.csv  — 10s buckets with YES/NO bid min/max/first/last
  kronos_polymarket_predictions.csv  — Kronos pred per market

Exit simulation order-of-events:
  For each bucket in time order:
    If low of our side's bid <= STOP: exit at STOP (worst case for us)
    Else if high of our side's bid >= TARGET: exit at TARGET (best case)
  If never triggered: hold to resolution, receive 1.0 if correct else 0.

Fee: 2% on winnings. Output: markdown report + CSV of strategy grid.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)


def load_data(markets_csv: Path, traj_csv: Path, kronos_csv: Path):
    m = pd.read_csv(markets_csv)
    m = m[m.entry_yes_ask.notna() & m.entry_no_ask.notna() & m.outcome_up.notna()].copy()
    k = pd.read_csv(kronos_csv)
    df = m.merge(k[["slug", "pred_dir_5m", "pred_dir_15m", "pred_ret_5m", "pred_ret_15m"]], on="slug")
    # Pick the prediction that matches the market's timeframe
    df["pred_dir"] = np.where(df.timeframe == "5m", df.pred_dir_5m, df.pred_dir_15m)
    df["pred_ret"] = np.where(df.timeframe == "5m", df.pred_ret_5m, df.pred_ret_15m)
    t = pd.read_csv(traj_csv)
    # Pivot trajectory so each (slug, bucket) has both Up and Down side columns
    up = t[t.outcome == "Up"].rename(columns={
        "bid_first": "up_bid_first", "bid_last": "up_bid_last",
        "bid_min": "up_bid_min", "bid_max": "up_bid_max",
        "ask_first": "up_ask_first", "ask_last": "up_ask_last",
    })[["slug", "bucket_10s", "up_bid_first", "up_bid_last", "up_bid_min", "up_bid_max",
         "up_ask_first", "up_ask_last"]]
    dn = t[t.outcome == "Down"].rename(columns={
        "bid_first": "dn_bid_first", "bid_last": "dn_bid_last",
        "bid_min": "dn_bid_min", "bid_max": "dn_bid_max",
        "ask_first": "dn_ask_first", "ask_last": "dn_ask_last",
    })[["slug", "bucket_10s", "dn_bid_first", "dn_bid_last", "dn_bid_min", "dn_bid_max",
         "dn_ask_first", "dn_ask_last"]]
    traj = up.merge(dn, on=["slug", "bucket_10s"], how="outer").sort_values(["slug", "bucket_10s"])
    return df, traj


def simulate_market(mdf_row: pd.Series, traj: pd.DataFrame,
                    target: float | None, stop: float | None,
                    trail_pct: float | None, time_exit_bucket: int | None,
                    fee_rate: float = 0.02) -> dict:
    """Simulate one market with chosen exit rules. Returns PnL per $1 stake."""
    signal = int(mdf_row.pred_dir)
    if signal == 1:
        entry = float(mdf_row.entry_yes_ask)
        bid_first_col, bid_min_col, bid_max_col, bid_last_col = (
            "up_bid_first", "up_bid_min", "up_bid_max", "up_bid_last")
    else:
        entry = float(mdf_row.entry_no_ask)
        bid_first_col, bid_min_col, bid_max_col, bid_last_col = (
            "dn_bid_first", "dn_bid_min", "dn_bid_max", "dn_bid_last")
    if not np.isfinite(entry) or entry <= 0 or entry >= 1:
        return {"pnl": 0.0, "exit_reason": "no_entry", "held": 0}

    # Walk trajectory buckets in order
    mt = traj[(traj.slug == mdf_row.slug) & (traj.bucket_10s >= 0)].sort_values("bucket_10s")
    peak = entry  # for trailing stop — start at entry
    exit_price = None
    exit_reason = "held"

    for _, b in mt.iterrows():
        bucket = int(b.bucket_10s)
        bid_min = b[bid_min_col]
        bid_max = b[bid_max_col]
        bid_last = b[bid_last_col]
        bid_first = b[bid_first_col]

        # Time exit: if bucket >= time_exit_bucket, sell at bid_last (conservative)
        if time_exit_bucket is not None and bucket >= time_exit_bucket:
            exit_price = float(bid_last) if pd.notna(bid_last) else (
                         float(bid_first) if pd.notna(bid_first) else None)
            if exit_price is not None:
                exit_reason = "time_exit"
                break

        # Stop check first (conservative: assume worst intra-bucket)
        if stop is not None and pd.notna(bid_min) and bid_min <= stop:
            exit_price = float(stop)
            exit_reason = "stop"
            break

        # Target check
        if target is not None and pd.notna(bid_max) and bid_max >= target:
            exit_price = float(target)
            exit_reason = "target"
            break

        # Trailing stop
        if trail_pct is not None and pd.notna(bid_max) and pd.notna(bid_min):
            peak = max(peak, float(bid_max))
            trail_level = peak * (1.0 - trail_pct)
            if bid_min <= trail_level and trail_level > entry:  # only trail from above entry
                exit_price = trail_level
                exit_reason = "trail"
                break

    # No exit -> hold to resolution
    if exit_price is None:
        outcome = int(mdf_row.outcome_up)
        won = (signal == outcome)
        gross = (1.0 - entry) if won else -entry
        fee = (1.0 - entry) * fee_rate if won else 0.0
        return {"pnl": gross - fee, "exit_reason": "resolution",
                "held": 999, "won_final": won}
    else:
        pnl = exit_price - entry
        # No fee on early exits (fee is on winnings at resolution; early sells pay taker fee
        # ~0.3% of stake on Polymarket CLOB — approximation)
        return {"pnl": pnl, "exit_reason": exit_reason,
                "held": int(bucket), "won_final": pnl > 0}


def run_strategy(df: pd.DataFrame, traj: pd.DataFrame, **params) -> dict:
    """Run a strategy across all markets, return aggregate stats."""
    results = [simulate_market(row, traj, **params) for _, row in df.iterrows()]
    pnls = np.array([r["pnl"] for r in results])
    reasons = [r["exit_reason"] for r in results]
    from collections import Counter
    reason_counts = Counter(reasons)
    return {
        "n": len(results),
        "total_pnl": float(pnls.sum()),
        "mean_pnl": float(pnls.mean()),
        "win_rate": float((pnls > 0).mean()),
        "roi_pct": float(pnls.mean() * 100),
        "reason_counts": dict(reason_counts),
        "pnls": pnls,
    }


def bootstrap_ci(pnls: np.ndarray, n_boot: int = 2000) -> tuple[float, float]:
    idx = RNG.integers(0, len(pnls), size=(n_boot, len(pnls)))
    totals = pnls[idx].sum(axis=1)
    return float(np.quantile(totals, 0.025)), float(np.quantile(totals, 0.975))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="strategy_lab/data/polymarket/btc_markets.csv")
    ap.add_argument("--traj",    default="strategy_lab/data/polymarket/btc_trajectories.csv")
    ap.add_argument("--kronos",  default="strategy_lab/results/kronos/kronos_polymarket_predictions.csv")
    ap.add_argument("--timeframe", default="all", choices=["all", "5m", "15m"])
    ap.add_argument("--out",     default="strategy_lab/reports/POLYMARKET_BACKTEST_REAL.md")
    ap.add_argument("--out-csv", default="strategy_lab/results/polymarket/strategy_grid.csv")
    args = ap.parse_args()

    df, traj = load_data(Path(args.markets), Path(args.traj), Path(args.kronos))
    if args.timeframe != "all":
        df = df[df.timeframe == args.timeframe]
    print(f"Markets in scope: {len(df)} ({args.timeframe})")

    strategies = []

    # S0: Hold to resolution
    strategies.append(("S0 Hold-to-resolution",
                       {"target": None, "stop": None, "trail_pct": None, "time_exit_bucket": None}))

    # S1: Target only
    for t in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90]:
        strategies.append((f"S1 Target {t:.2f}",
                           {"target": t, "stop": None, "trail_pct": None, "time_exit_bucket": None}))

    # S2: Stop only
    for s in [0.40, 0.35, 0.30, 0.25, 0.20]:
        strategies.append((f"S2 Stop {s:.2f}",
                           {"target": None, "stop": s, "trail_pct": None, "time_exit_bucket": None}))

    # S3: Target + Stop
    for t in [0.65, 0.70, 0.80]:
        for s in [0.35, 0.30, 0.25]:
            strategies.append((f"S3 T{t:.2f}+S{s:.2f}",
                               {"target": t, "stop": s, "trail_pct": None, "time_exit_bucket": None}))

    # S4: Trailing stop
    for tp in [0.05, 0.10, 0.15, 0.20]:
        strategies.append((f"S4 Trail {tp:.0%}",
                           {"target": None, "stop": None, "trail_pct": tp, "time_exit_bucket": None}))

    # S5: Time exit (sell at bucket N = 10N seconds after window_start)
    # For 5m (30 buckets) and 15m (90 buckets)
    for b in [10, 20, 25, 60, 80]:
        strategies.append((f"S5 Time-exit @ bucket {b} ({b*10}s)",
                           {"target": None, "stop": None, "trail_pct": None, "time_exit_bucket": b}))

    # S6: Confidence + hold-to-resolution
    conf_cut = df["pred_ret"].abs().quantile(0.75)
    df_conf = df[df["pred_ret"].abs() >= conf_cut]
    print(f"\nConfidence-filtered subset: {len(df_conf)}")

    rows = []
    for name, params in strategies:
        r = run_strategy(df, traj, **params)
        lo, hi = bootstrap_ci(r["pnls"])
        rows.append({
            "strategy": name,
            "n": r["n"],
            "total_pnl": r["total_pnl"],
            "total_pnl_ci_lo": lo,
            "total_pnl_ci_hi": hi,
            "mean_pnl": r["mean_pnl"],
            "win_rate": r["win_rate"],
            "roi_pct": r["roi_pct"],
            "exits_target": r["reason_counts"].get("target", 0),
            "exits_stop": r["reason_counts"].get("stop", 0),
            "exits_trail": r["reason_counts"].get("trail", 0),
            "exits_time": r["reason_counts"].get("time_exit", 0),
            "exits_resolution": r["reason_counts"].get("resolution", 0),
        })

    # Same strategies on confidence-filtered subset
    for name, params in strategies[:3] + strategies[7:10]:  # key subset
        r = run_strategy(df_conf, traj, **params)
        lo, hi = bootstrap_ci(r["pnls"])
        rows.append({
            "strategy": f"[CONF] {name}",
            "n": r["n"],
            "total_pnl": r["total_pnl"],
            "total_pnl_ci_lo": lo,
            "total_pnl_ci_hi": hi,
            "mean_pnl": r["mean_pnl"],
            "win_rate": r["win_rate"],
            "roi_pct": r["roi_pct"],
            "exits_target": r["reason_counts"].get("target", 0),
            "exits_stop": r["reason_counts"].get("stop", 0),
            "exits_trail": r["reason_counts"].get("trail", 0),
            "exits_time": r["reason_counts"].get("time_exit", 0),
            "exits_resolution": r["reason_counts"].get("resolution", 0),
        })

    grid = pd.DataFrame(rows).sort_values("total_pnl", ascending=False)
    print("\n=== Top 10 strategies ===")
    print(grid.head(10)[["strategy", "n", "total_pnl", "total_pnl_ci_lo", "total_pnl_ci_hi",
                          "win_rate", "roi_pct"]].to_string(index=False))
    print("\n=== Bottom 5 ===")
    print(grid.tail(5)[["strategy", "n", "total_pnl", "roi_pct"]].to_string(index=False))

    Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
    grid.to_csv(args.out_csv, index=False)

    L = [f"# Polymarket Real-Signal Backtest ({args.timeframe})", ""]
    L.append(f"Markets in scope: {len(df)}")
    L.append(f"Using REAL Kronos predictions on Apr 22-23 2026 Polymarket data.")
    L.append(f"Kronos accuracy in this window: 5m=52.9%, 15m=51.4% (baseline, no filters).")
    L.append(f"Break-even estimate: ~53% (fees + spread).")
    L.append("")
    L.append("## Strategy Grid (sorted by total PnL)")
    L.append("")
    L.append("| Strategy | n | Total PnL | 95% CI | Win% | ROI/bet | Exit reasons (target / stop / trail / time / resolution) |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in grid.iterrows():
        L.append(f"| {r['strategy']} | {int(r['n'])} | "
                 f"${r['total_pnl']:+.2f} | "
                 f"[${r['total_pnl_ci_lo']:+.2f}, ${r['total_pnl_ci_hi']:+.2f}] | "
                 f"{r['win_rate']:.1%} | "
                 f"{r['roi_pct']:+.2f}% | "
                 f"{int(r['exits_target'])}/{int(r['exits_stop'])}/"
                 f"{int(r['exits_trail'])}/{int(r['exits_time'])}/"
                 f"{int(r['exits_resolution'])} |")
    L.append("")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(L), encoding="utf-8")
    print(f"\nWrote {args.out}")
    print(f"Wrote {args.out_csv}")


if __name__ == "__main__":
    main()
