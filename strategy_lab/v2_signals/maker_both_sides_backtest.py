"""A1 Maker-on-both-sides backtest.

Quote a maker BUY on both YES and NO simultaneously at start-of-window:
  yes_quote = yes_bid_0 + tick
  no_quote  = no_bid_0  + tick

For each market, walk the book trajectory bucket-by-bucket:
  Fill on YES if any later bucket has yes_ask <= yes_quote.
  Fill on NO  if any later bucket has no_ask  <= no_quote.

At slot_end, settle:
  YES fill: payoff = (1 if outcome=Up else 0) - yes_quote  per share
  NO fill:  payoff = (1 if outcome=Down else 0) - no_quote per share
  shares per side = $25 / quote_price

Output: per-market PnL by fill-pattern bucket (none / yes-only / no-only / both),
plus aggregate ROI / hit / sharpe.

Caveats:
  - Approximation: maker fill detected by ask <= quote. Underestimates fills
    that happen between snapshots; no trade-tape price data to be precise.
  - No fee model. Polymarket maker fees are 0% historically; verify before live.
  - No queue position model. We assume FIFO at our price level — overoptimistic
    if many makers cluster at bid_0 + tick.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, DATA_DIR

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results" / "polymarket"

NOTIONAL = 25.0
TICKS = [0.01, 0.02]


def load_book_traj(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_book_depth_v3.csv"
    return pd.read_csv(p, usecols=[
        "slug", "timeframe", "bucket_10s", "outcome",
        "bid_price_0", "ask_price_0",
    ])


def simulate_asset(asset: str, tick: float) -> pd.DataFrame:
    feats = load_features(asset)
    feats = feats.dropna(subset=["outcome_up", "entry_yes_ask", "entry_no_ask"])
    book = load_book_traj(asset)

    # Build initial bid (bucket 0) per (slug, outcome)
    init = book[book["bucket_10s"] == 0][["slug", "outcome", "bid_price_0", "ask_price_0"]]
    init = init.rename(columns={"bid_price_0": "init_bid", "ask_price_0": "init_ask"})
    init_yes = init[init["outcome"] == "Up"].set_index("slug")[["init_bid", "init_ask"]]
    init_no  = init[init["outcome"] == "Down"].set_index("slug")[["init_bid", "init_ask"]]

    # For each later bucket, check if ask <= quote (= init_bid + tick)
    later = book[book["bucket_10s"] > 0]
    later_yes = later[later["outcome"] == "Up"]
    later_no  = later[later["outcome"] == "Down"]

    # Per-slug min ask after bucket 0
    min_ask_yes = later_yes.groupby("slug")["ask_price_0"].min()
    min_ask_no  = later_no.groupby("slug")["ask_price_0"].min()

    rows = []
    for _, row in feats.iterrows():
        slug = row["slug"]
        if slug not in init_yes.index or slug not in init_no.index:
            continue

        yes_init_bid = init_yes.loc[slug, "init_bid"]
        no_init_bid  = init_no.loc[slug, "init_bid"]
        yes_quote = yes_init_bid + tick
        no_quote  = no_init_bid  + tick

        # Don't quote above the current ask (would be a taker)
        yes_init_ask = init_yes.loc[slug, "init_ask"]
        no_init_ask  = init_no.loc[slug, "init_ask"]
        if yes_quote >= yes_init_ask:
            yes_quote = float("nan")  # no valid maker quote (spread too tight)
        if no_quote  >= no_init_ask:
            no_quote  = float("nan")

        # Fill detection
        yes_min = min_ask_yes.get(slug, float("nan"))
        no_min  = min_ask_no.get(slug, float("nan"))
        yes_filled = pd.notna(yes_quote) and pd.notna(yes_min) and yes_min <= yes_quote
        no_filled  = pd.notna(no_quote)  and pd.notna(no_min)  and no_min  <= no_quote

        # Settlement
        outcome_up = bool(row["outcome_up"])
        yes_pnl = 0.0
        no_pnl = 0.0
        cost = 0.0
        if yes_filled:
            shares_yes = NOTIONAL / yes_quote
            yes_pnl = shares_yes * ((1.0 if outcome_up else 0.0) - yes_quote)
            cost += NOTIONAL
        if no_filled:
            shares_no = NOTIONAL / no_quote
            no_pnl = shares_no * ((0.0 if outcome_up else 1.0) - no_quote)
            cost += NOTIONAL

        fill_pattern = "both" if (yes_filled and no_filled) else \
                       "yes_only" if yes_filled else \
                       "no_only" if no_filled else "none"

        rows.append({
            "asset": asset,
            "timeframe": row["timeframe"],
            "slug": slug,
            "tick": tick,
            "yes_quote": yes_quote,
            "no_quote": no_quote,
            "yes_filled": yes_filled,
            "no_filled": no_filled,
            "fill_pattern": fill_pattern,
            "outcome_up": int(outcome_up),
            "yes_pnl": yes_pnl,
            "no_pnl": no_pnl,
            "total_pnl": yes_pnl + no_pnl,
            "cost": cost,
        })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0:
        return {}
    pnl = df["total_pnl"]
    cost = df["cost"]
    won = (pnl > 0).sum()
    none = (df["fill_pattern"] == "none").sum()
    one  = ((df["fill_pattern"] == "yes_only") | (df["fill_pattern"] == "no_only")).sum()
    both = (df["fill_pattern"] == "both").sum()
    fired = n - none
    sharpe = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    return {
        "label": label,
        "n_markets": n,
        "n_fired": fired,
        "fire_pct": round(fired / n * 100, 1) if n else 0,
        "fill_none": none,
        "fill_one_side": one,
        "fill_both": both,
        "total_pnl": round(pnl.sum(), 2),
        "total_cost": round(cost.sum(), 2),
        "roi_pct": round(pnl.sum() / cost.sum() * 100, 2) if cost.sum() > 0 else 0,
        "hit_pct_fired": round(won / fired * 100, 1) if fired else 0,
        "sharpe": round(sharpe, 2),
    }


def main():
    all_sims = []
    for tick in TICKS:
        for asset in ASSETS:
            sim = simulate_asset(asset, tick)
            all_sims.append(sim)
    full = pd.concat(all_sims, ignore_index=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "maker_both_sides_backtest.csv"
    full.to_csv(out, index=False)
    print(f"Wrote {out}")

    # Summary table
    print("\n=== Summary by tick × asset × tf ===")
    summaries = []
    for tick in TICKS:
        for asset in (*ASSETS, "ALL"):
            for tf in ("5m", "15m", "ALL"):
                sub = full[full["tick"] == tick]
                if asset != "ALL":
                    sub = sub[sub["asset"] == asset]
                if tf != "ALL":
                    sub = sub[sub["timeframe"] == tf]
                if len(sub) == 0:
                    continue
                s = summarize(sub, f"tick={tick} {asset} {tf}")
                summaries.append(s)
    sum_df = pd.DataFrame(summaries)
    print(sum_df.to_string(index=False))

    print("\n=== Best 10 by ROI ===")
    print(sum_df.nlargest(10, "roi_pct").to_string(index=False))

    # Specifically: how often does both-side fill happen, and what's its per-fill PnL?
    both_rows = full[full["fill_pattern"] == "both"]
    if len(both_rows) > 0:
        print(f"\n=== Both-side fills: n={len(both_rows)}, mean PnL=${both_rows['total_pnl'].mean():.4f}, "
              f"total=${both_rows['total_pnl'].sum():.2f} ===")


if __name__ == "__main__":
    main()
