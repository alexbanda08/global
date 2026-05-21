"""Trade-tape fill detector for mint-and-sell v3.

Replaces the conservative `fill_status_and_exit_bid` (which only fires when
best_bid_opp reaches our ask) with direct taker-print evidence from the
Polymarket trades parquet.

A maker SELL at price P fills when a TAKER places a BUY that lifts asks at
price >= P. We observe these as rows in the trades parquet with:
    side == 'BUY' (taker side) AND price >= P

Two fill models:
  - OPTIMISTIC: filled if ANY qualifying taker-buy in [ts, ts+60s].
                Upper bound; assumes our order at the front of the queue
                or queue ahead is cleared.
  - QUEUE-AWARE: filled if cumulative taker-buy volume at price >= P within
                 60s exceeds (queue_ahead_at_post + 0.5*our_size). The
                 queue_ahead is approximated as size_at_or_below_our_price
                 at the moment of post.

For mint-and-sell, our size per fire is $2.5 / P shares (5 shares at $0.50,
2.5 shares at $1.0). Queue ahead is typically 100-2000+ shares (resting
makers at the same price).
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_resolutions  # noqa: E402

WAIT_S = 60
WAIT_US = WAIT_S * 1_000_000


@dataclass
class FillResult:
    """Per-leg fill outcome under both models."""
    optimistic_filled: bool
    queue_aware_filled: bool
    taker_buy_volume: float       # total taker BUY volume at price >= our_ask in [ts, ts+60]
    queue_ahead: float            # estimated shares ahead at post time
    first_fill_us: int            # us of first qualifying taker-buy print, -1 if none
    n_qualifying_prints: int


def load_trades_for_asset(asset: str) -> pd.DataFrame:
    """Load Polymarket trades parquet for one asset and pre-sort by (slug, outcome, ts)."""
    p = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset.lower()}.parquet"
    df = pd.read_parquet(p, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"])
    df = df.sort_values(["slug", "outcome", "timestamp_us"]).reset_index(drop=True)
    return df


def index_trades_by_key(trades: pd.DataFrame) -> dict:
    """Build (slug, outcome) -> np.array of (ts, price, size, is_taker_buy) for fast lookup."""
    out = {}
    is_buy = (trades["side"].str.lower().values == "buy")
    arr = np.column_stack([
        trades["timestamp_us"].values.astype(np.int64),
        trades["price"].values.astype(np.float64),
        trades["size"].values.astype(np.float64),
        is_buy.astype(np.int8),
    ])
    for (slug, outcome), grp in trades.groupby(["slug", "outcome"], sort=False):
        idx = grp.index.values
        out[(slug, outcome)] = arr[idx]
    return out


def detect_fill(
    trades_arr: np.ndarray,            # shape (N, 4): ts, price, size, is_taker_buy
    target_ask: float,
    start_us: int,
    our_size_shares: float,
    queue_ahead: float = 0.0,
    wait_us: int = WAIT_US,
) -> FillResult:
    """Returns optimistic + queue-aware fill verdict for one leg."""
    if trades_arr is None or len(trades_arr) == 0:
        return FillResult(False, False, 0.0, queue_ahead, -1, 0)

    ts = trades_arr[:, 0]
    end_us = start_us + wait_us
    mask = (ts >= start_us) & (ts <= end_us)
    if not mask.any():
        return FillResult(False, False, 0.0, queue_ahead, -1, 0)

    window = trades_arr[mask]
    qual = (window[:, 1] >= target_ask) & (window[:, 3] == 1)  # taker BUY at price >= our ask
    if not qual.any():
        return FillResult(False, False, 0.0, queue_ahead, -1, 0)

    qual_window = window[qual]
    total_buy_vol = float(qual_window[:, 2].sum())
    first_fill_us = int(qual_window[0, 0])
    n_prints = int(qual.sum())

    optimistic = True
    queue_aware = total_buy_vol >= (queue_ahead + 0.5 * our_size_shares)

    return FillResult(optimistic, queue_aware, total_buy_vol, queue_ahead, first_fill_us, n_prints)


def estimate_queue_ahead(size_at_best: float) -> float:
    """Approximate queue ahead at best ask, assuming we joined the back of the queue.

    `size_at_best` comes from the opportunities parquet (size_up / size_dn).
    Conservative: assume entire visible size is ahead of us.
    """
    return float(size_at_best) if np.isfinite(size_at_best) else 0.0


def compare_detectors(
    asset: str,
    cell: str,
    n_sample: int = 2000,
    notional: float = 2.5,
    seed: int = 42,
    pc_path: Path | None = None,
) -> dict:
    """Replays v2 sample opportunities through the trade-tape detector and
    compares fill rates vs the bid-reaches-ask baseline (already in
    policy_compare.parquet)."""
    R = ROOT / "data" / "v4" / "canonical" / "_results"
    op_path = R / f"mint_and_sell_v2_{cell}_2026_05_16" / "opportunities.parquet"
    pc_path = pc_path or R / f"mint_and_sell_v2_{cell}_2026_05_16" / "policy_compare.parquet"

    pc = pd.read_parquet(pc_path)
    op = pd.read_parquet(op_path)
    op = op.merge(pc[["slug", "ts"]], on=["slug", "ts"], how="inner")
    op = op.drop_duplicates(subset=["slug", "ts"]).reset_index(drop=True)

    res = load_resolutions(assets=[asset.upper()], timeframes=[cell.split("_")[1]])[["slug", "outcome"]].drop_duplicates(subset="slug")
    op = op.merge(res, on="slug", how="inner")

    # Filter to slugs WITH trades coverage (trades parquet has its own window)
    tr_slugs_path = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset.lower()}.parquet"
    tr_slugs = set(pd.read_parquet(tr_slugs_path, columns=["slug"])["slug"].unique())
    pre = len(op)
    op = op[op.slug.isin(tr_slugs)].reset_index(drop=True)
    print(f"[{cell}] op slugs intersected with trades: {pre:,} -> {len(op):,}", flush=True)

    if len(op) > n_sample:
        op = op.sample(n=n_sample, random_state=seed).reset_index(drop=True)

    print(f"[{cell}] loaded {len(op):,} sample fires, {op.slug.nunique():,} slugs", flush=True)
    print(f"[{cell}] loading trades parquet...", flush=True)
    trades = load_trades_for_asset(asset)
    print(f"[{cell}] indexing {len(trades):,} trades by (slug, outcome)...", flush=True)
    tidx = index_trades_by_key(trades)
    del trades
    print(f"[{cell}] indexed {len(tidx):,} (slug, outcome) keys", flush=True)

    results = []
    for r in op.itertuples(index=False):
        slug = r.slug
        ts = int(r.ts)
        our_shares_up = notional / max(r.ask_up, 0.001)
        our_shares_dn = notional / max(r.ask_dn, 0.001)
        q_up = estimate_queue_ahead(r.size_up)
        q_dn = estimate_queue_ahead(r.size_dn)

        fu = detect_fill(tidx.get((slug, "Up")), r.ask_up, ts, our_shares_up, q_up)
        fd = detect_fill(tidx.get((slug, "Down")), r.ask_dn, ts, our_shares_dn, q_dn)

        results.append({
            "slug": slug, "ts": ts, "outcome": r.outcome,
            "ask_up": r.ask_up, "ask_dn": r.ask_dn,
            "size_up": r.size_up, "size_dn": r.size_dn,
            "fill_up_opt": fu.optimistic_filled,
            "fill_dn_opt": fd.optimistic_filled,
            "fill_up_q": fu.queue_aware_filled,
            "fill_dn_q": fd.queue_aware_filled,
            "buy_vol_up": fu.taker_buy_volume,
            "buy_vol_dn": fd.taker_buy_volume,
            "queue_ahead_up": fu.queue_ahead,
            "queue_ahead_dn": fd.queue_ahead,
        })

    df = pd.DataFrame(results)
    df["scenario_opt"] = np.where(
        df.fill_up_opt & df.fill_dn_opt, "BOTH",
        np.where(~df.fill_up_opt & ~df.fill_dn_opt, "NEITHER",
                 np.where(df.fill_up_opt, "Down_HELD", "Up_HELD"))
    )
    df["scenario_q"] = np.where(
        df.fill_up_q & df.fill_dn_q, "BOTH",
        np.where(~df.fill_up_q & ~df.fill_dn_q, "NEITHER",
                 np.where(df.fill_up_q, "Down_HELD", "Up_HELD"))
    )

    pc_join = pc[["slug", "ts", "scenario"]].rename(columns={"scenario": "scenario_bid"})
    df = df.merge(pc_join, on=["slug", "ts"], how="left")

    print(f"\n=== {cell}: fill-rate comparison (n={len(df)}) ===")
    for label in ("scenario_bid", "scenario_opt", "scenario_q"):
        vc = df[label].value_counts(normalize=True) * 100
        print(f"  {label}: BOTH={vc.get('BOTH', 0):.1f}%  NEITHER={vc.get('NEITHER', 0):.1f}%  "
              f"Up_HELD={vc.get('Up_HELD', 0):.1f}%  Down_HELD={vc.get('Down_HELD', 0):.1f}%")

    out_dir = R / f"mint_and_sell_v3_tradetape_{cell}_2026_05_16"
    out_dir.mkdir(exist_ok=True)
    df.to_parquet(out_dir / "fill_compare.parquet", index=False)
    print(f"  → wrote {out_dir / 'fill_compare.parquet'}", flush=True)
    return {"cell": cell, "n": len(df), "df": df}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="sol_15m", help="asset_tf e.g. sol_15m, btc_5m")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--notional", type=float, default=2.5)
    args = ap.parse_args()
    asset = args.cell.split("_")[0]
    compare_detectors(asset, args.cell, n_sample=args.n, notional=args.notional)
