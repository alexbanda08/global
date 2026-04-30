"""Exit-variant backtest — tries different exit policies beyond hold-to-resolution.

Exits tested:
  - hold (baseline): hold to resolution
  - tp_X: take profit if YES (or NO if shorting up) price reaches X (e.g. 0.80, 0.90)
  - sl_X: stop loss if our side falls to X
  - trail_X: trailing stop, lock in (peak - X) profit
  - oppo_flip: exit if at any 10s bucket the price crosses 0.5 against us

For each market, walk the YES book trajectory bucket-by-bucket. Apply each exit rule.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, DATA_DIR

NOTIONAL = 25.0
FEE = 0.02


def load_book(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_book_depth_v3.csv"
    return pd.read_csv(p, usecols=["slug", "bucket_10s", "outcome", "ask_price_0", "bid_price_0"])


def per_market_pnl(row, traj_yes, traj_no, exit_rule, params):
    """traj_yes / traj_no: per-bucket DataFrames with bucket_10s, ask_price_0, bid_price_0."""
    pred_up = row["ret_5m"] > 0
    if pred_up:
        # Long YES at entry_yes_ask
        entry_px = row["entry_yes_ask"]
        traj = traj_yes
        winning_outcome = (row["outcome_up"] == 1)
    else:
        entry_px = row["entry_no_ask"]
        traj = traj_no
        winning_outcome = (row["outcome_up"] == 0)

    if pd.isna(entry_px) or entry_px <= 0 or entry_px >= 1:
        return None

    shares = NOTIONAL / entry_px
    # Walk traj from bucket >0
    traj_sorted = traj.sort_values("bucket_10s")
    bucket_prices = traj_sorted[["bucket_10s", "bid_price_0", "ask_price_0"]].values
    exit_px = None
    exit_reason = "hold"

    if exit_rule == "hold":
        pass  # Hold to resolution
    elif exit_rule.startswith("tp_"):
        thr = params["tp"]
        for b, bid, ask in bucket_prices:
            if b == 0:
                continue
            # Take profit: if our side's BID >= thr, we can exit at thr+
            if pd.notna(bid) and bid >= thr:
                exit_px = bid
                exit_reason = "tp"
                break
    elif exit_rule.startswith("sl_"):
        thr = params["sl"]
        for b, bid, ask in bucket_prices:
            if b == 0:
                continue
            if pd.notna(bid) and bid <= thr:
                exit_px = bid
                exit_reason = "sl"
                break
    elif exit_rule.startswith("trail_"):
        # Trailing stop: track peak bid, exit when bid drops by X
        peak = entry_px
        drop = params["trail"]
        for b, bid, ask in bucket_prices:
            if b == 0:
                continue
            if pd.notna(bid):
                peak = max(peak, bid)
                if bid <= peak - drop:
                    exit_px = bid
                    exit_reason = "trail"
                    break
    elif exit_rule == "oppo_flip":
        # Exit if our side's bid crosses 0.5 against us
        for b, bid, ask in bucket_prices:
            if b == 0:
                continue
            if pd.notna(bid) and bid < 0.5:
                exit_px = bid
                exit_reason = "flip"
                break

    if exit_px is not None:
        pnl_share = exit_px - entry_px
    else:
        # Hold to resolution
        pnl_share = (1.0 - entry_px) if winning_outcome else (-entry_px)

    pnl = shares * pnl_share
    pnl_after = pnl * (1 - FEE) if pnl > 0 else pnl
    return {"pnl": pnl_after, "exit_reason": exit_reason, "exit_px": exit_px}


def evaluate(feats, books_yes, books_no, exit_rule, params, label):
    rows = []
    for _, r in feats.iterrows():
        slug = r["slug"]
        ty = books_yes.get(slug)
        tn = books_no.get(slug)
        if ty is None or tn is None:
            continue
        out = per_market_pnl(r, ty, tn, exit_rule, params)
        if out:
            rows.append(out)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    n = len(df)
    pnl = df["pnl"]
    return {
        "label": label,
        "n": n,
        "win_pct": round((pnl > 0).mean() * 100, 1),
        "total_pnl": round(pnl.sum(), 2),
        "roi_pct": round(pnl.sum() / (NOTIONAL * n) * 100, 2),
        "hit_pct": None,  # not direction-based
        "early_exit_pct": round((df["exit_reason"] != "hold").mean() * 100, 1),
        "tp_pct": round((df["exit_reason"] == "tp").mean() * 100, 1),
        "sl_pct": round((df["exit_reason"] == "sl").mean() * 100, 1),
        "trail_pct": round((df["exit_reason"] == "trail").mean() * 100, 1),
    }


def main():
    rows = []
    for asset in ASSETS:
        feats = load_features(asset).dropna(subset=["outcome_up", "ret_5m", "entry_yes_ask", "entry_no_ask"])
        # Apply q10 filter
        thr = feats["ret_5m"].abs().quantile(0.90)
        feats_q10 = feats[feats["ret_5m"].abs() >= thr]
        book = load_book(asset)
        # Pre-build per-slug trajectories
        book_yes_sub = book[book["outcome"] == "Up"]
        book_no_sub = book[book["outcome"] == "Down"]
        bys = {slug: g for slug, g in book_yes_sub.groupby("slug")}
        bns = {slug: g for slug, g in book_no_sub.groupby("slug")}

        # Test exit variants
        configs = [
            ("hold",        {}),
            ("tp_70",       {"tp": 0.70}),
            ("tp_80",       {"tp": 0.80}),
            ("tp_90",       {"tp": 0.90}),
            ("tp_95",       {"tp": 0.95}),
            ("sl_30",       {"sl": 0.30}),
            ("sl_40",       {"sl": 0.40}),
            ("trail_5",     {"trail": 0.05}),
            ("trail_10",    {"trail": 0.10}),
            ("trail_15",    {"trail": 0.15}),
            ("oppo_flip",   {}),
        ]
        for rule, params in configs:
            for tf in ("5m", "15m", "ALL"):
                fsub = feats_q10
                if tf != "ALL":
                    fsub = fsub[fsub["timeframe"] == tf]
                res = evaluate(fsub, bys, bns, rule, params, f"{asset} {tf} q10 {rule}")
                if res:
                    res.update({"asset": asset, "tf": tf, "rule": rule})
                    rows.append(res)

    df = pd.DataFrame(rows)
    print(f"\n=== Exit variants × asset × tf × q10 ===\n")
    # Per asset, all rules in tf=ALL
    for asset in ASSETS:
        print(f"--- {asset.upper()} ALL ---")
        sub = df[(df["asset"] == asset) & (df["tf"] == "ALL")]
        print(sub[["rule", "n", "win_pct", "roi_pct", "early_exit_pct", "tp_pct", "sl_pct", "trail_pct"]].to_string(index=False))
        print()

    print("=== Top 20 by ROI ===")
    print(df.nlargest(20, "roi_pct")[["asset", "tf", "rule", "n", "win_pct", "roi_pct", "early_exit_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
