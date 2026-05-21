"""Search the trade-flow features dataset for ANY profitable direction rule.

We have:
  cache/_f2_trade_flow_features.parquet — 7,100 F2 fires + 366,405 controls
  with n_trades_5s, flow_imbalance_5s, etc.

We have chainlink RTDS to compute outcomes for every (slug, moment).

Test all combinations:
  - High vs low n_trades_5s threshold
  - Positive vs negative flow_imbalance threshold
  - Direction = follow-flow vs fade-flow

Then compute hold-to-settlement PnL for each combo.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import (  # noqa: E402
    load_chainlink_asof, asof_strict,
    load_orderbook_l25_streaming,
)

CACHE = Path(__file__).resolve().parent / "cache"
WINDOW_S = {"5m": 300, "15m": 900}
FEE = 0.07


def parse_slug(slug):
    parts = slug.split("-")
    if len(parts) != 4 or parts[1] != "updown":
        return None
    return parts[0].upper(), parts[2], int(parts[3])


def derive_outcome(slug, rtds_cache):
    info = parse_slug(slug)
    if info is None: return None
    asset, tf, slot_start = info
    slot_end = slot_start + WINDOW_S[tf]
    ts, px = rtds_cache.get(asset, (None, None))
    if ts is None or len(ts) == 0: return None
    strike = asof_strict(ts, px, slot_start * 1_000_000)
    settle = asof_strict(ts, px, slot_end * 1_000_000)
    if not (strike > 0 and settle > 0): return None
    return "Up" if settle > strike else "Down"


def hold_pnl(entry_px, won):
    if not (0 < entry_px < 1): return 0.0
    fee = FEE * entry_px * (1 - entry_px)
    return (1 - entry_px - fee) if won else (-entry_px - fee)


def main():
    print("Loading feature set ...")
    df = pd.read_parquet(CACHE / "_f2_trade_flow_features.parquet")
    print(f"  rows: {len(df):,} (fires + controls)")

    # Need to add book state (up_ask, dn_ask) at each moment to compute entries
    # Reload OB for all unique slugs
    slugs = sorted(df.slug.unique())
    print(f"Loading OB for {len(slugs)} slugs...")
    ob = load_orderbook_l25_streaming("btc", slugs=set(slugs))
    print(f"  loaded {len(ob)} (slug, outcome) groups")

    # Add winner column (chainlink-derived)
    print("Deriving outcomes ...")
    rtds = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}
    slug_winners = {s: derive_outcome(s, rtds) for s in slugs}
    df["winner"] = df.slug.map(slug_winners)
    df = df.dropna(subset=["winner"]).copy()
    print(f"  rows with outcome: {len(df):,}")

    # Add book state by searchsorted per slug
    print("Adding book state to each row (up_ask, dn_ask)...")
    df["up_ask"] = np.nan
    df["dn_ask"] = np.nan
    df["up_asz"] = np.nan
    df["dn_asz"] = np.nan
    for slug in slugs:
        sub_idx = df.index[df.slug == slug]
        if len(sub_idx) == 0: continue
        book_up = ob.get((slug, "Up"))
        book_dn = ob.get((slug, "Down"))
        if book_up is None or book_dn is None: continue
        ts_us = df.loc[sub_idx, "fire_ts_us"].values
        # Up
        ts_arr_u, ap_u, asz_u, _, _ = book_up
        pos_u = np.searchsorted(ts_arr_u, ts_us, side="right") - 1
        valid = pos_u >= 0
        up_ask_vals = np.where(valid, ap_u[np.clip(pos_u, 0, None), 0], np.nan)
        up_asz_vals = np.where(valid, asz_u[np.clip(pos_u, 0, None), 0], np.nan)
        df.loc[sub_idx, "up_ask"] = up_ask_vals
        df.loc[sub_idx, "up_asz"] = up_asz_vals
        # Down
        ts_arr_d, ap_d, asz_d, _, _ = book_dn
        pos_d = np.searchsorted(ts_arr_d, ts_us, side="right") - 1
        valid = pos_d >= 0
        dn_ask_vals = np.where(valid, ap_d[np.clip(pos_d, 0, None), 0], np.nan)
        dn_asz_vals = np.where(valid, asz_d[np.clip(pos_d, 0, None), 0], np.nan)
        df.loc[sub_idx, "dn_ask"] = dn_ask_vals
        df.loc[sub_idx, "dn_asz"] = dn_asz_vals

    # Sum asks
    df["sum_asks"] = df.up_ask + df.dn_ask
    df["max_asz"] = df[["up_asz", "dn_asz"]].max(axis=1)
    df = df.dropna(subset=["up_ask", "dn_ask"]).copy()
    print(f"  rows with book: {len(df):,}")

    # Filter to BTC and add offset_from_slot_start
    df["slot_start_s"] = df.slug.apply(
        lambda s: int(s.rsplit("-", 1)[1]) if s.startswith("btc-updown-") else np.nan
    )
    df = df.dropna(subset=["slot_start_s"]).copy()
    df["offset_s"] = (df.fire_ts_us // 1_000_000).astype(int) - df.slot_start_s.astype(int)

    # Compute PnL for both directions for ALL moments
    print("Computing per-row PnL for both fade and follow ...")

    # Follow-flow: if flow_imbalance > 0 (Up buyers winning), buy Up
    df["pick_follow"] = np.where(df.flow_imbalance_5s > 0, "Up", "Down")
    df["entry_follow"] = np.where(df.pick_follow == "Up", df.up_ask, df.dn_ask)
    df["won_follow"] = (df.pick_follow == df.winner)
    df["shares_follow"] = 1.0 / df.entry_follow.clip(lower=0.01)
    df["pnl_follow"] = df.apply(
        lambda r: r.shares_follow * hold_pnl(r.entry_follow, bool(r.won_follow))
        if 0 < r.entry_follow < 1 else 0.0,
        axis=1
    )

    # Fade-flow: opposite
    df["pick_fade"] = np.where(df.flow_imbalance_5s > 0, "Down", "Up")
    df["entry_fade"] = np.where(df.pick_fade == "Up", df.up_ask, df.dn_ask)
    df["won_fade"] = (df.pick_fade == df.winner)
    df["shares_fade"] = 1.0 / df.entry_fade.clip(lower=0.01)
    df["pnl_fade"] = df.apply(
        lambda r: r.shares_fade * hold_pnl(r.entry_fade, bool(r.won_fade))
        if 0 < r.entry_fade < 1 else 0.0,
        axis=1
    )

    print()
    print("=" * 100)
    print("Grand search: best threshold combination for FOLLOW-flow")
    print("=" * 100)
    print(f"{'n_tr':>5s} {'|flow|':>6s} {'sum':>5s} {'asz':>5s} {'off':>4s}  "
          f"{'n':>6s} {'WR%':>6s} {'mean':>8s} {'sum':>10s}")
    print("-" * 80)

    results = []
    for n_thr in (10, 30, 50, 100, 200):
        for flow_thr in (0.1, 0.2, 0.3, 0.5, 0.7):
            for sa_thr in (1.005, 1.010, 1.020):
                for asz_thr in (100, 500, 1000):
                    for off_thr in (60, 120, 240, 270):
                        mask = (
                            (df.n_trades_5s >= n_thr)
                            & (df.flow_imbalance_5s.abs() >= flow_thr)
                            & (df.sum_asks >= sa_thr)
                            & (df.max_asz >= asz_thr)
                            & (df.offset_s >= off_thr)
                        )
                        sub = df[mask]
                        if len(sub) < 30:
                            continue
                        # Follow
                        wr_f = sub.won_follow.mean()
                        mean_f = sub.pnl_follow.mean()
                        sum_f = sub.pnl_follow.sum()
                        # Fade
                        wr_fd = sub.won_fade.mean()
                        mean_fd = sub.pnl_fade.mean()
                        sum_fd = sub.pnl_fade.sum()
                        rec = {
                            "n_thr": n_thr, "flow_thr": flow_thr,
                            "sa_thr": sa_thr, "asz_thr": asz_thr,
                            "off_thr": off_thr, "n": len(sub),
                            "wr_follow": wr_f, "mean_follow": mean_f, "sum_follow": sum_f,
                            "wr_fade": wr_fd, "mean_fade": mean_fd, "sum_fade": sum_fd,
                        }
                        results.append(rec)

    if results:
        rdf = pd.DataFrame(results)
        print()
        print("TOP 10 by FOLLOW total PnL:")
        for r in rdf.sort_values("sum_follow", ascending=False).head(10).itertuples(index=False):
            print(f"  n>={r.n_thr} |flow|>={r.flow_thr:.1f} sum>={r.sa_thr} asz>={r.asz_thr} off>={r.off_thr}  "
                  f"n={r.n:5d}  WR={r.wr_follow*100:5.2f}%  mean=${r.mean_follow:+.4f}  "
                  f"total=${r.sum_follow:+.2f}")
        print()
        print("TOP 10 by FADE total PnL:")
        for r in rdf.sort_values("sum_fade", ascending=False).head(10).itertuples(index=False):
            print(f"  n>={r.n_thr} |flow|>={r.flow_thr:.1f} sum>={r.sa_thr} asz>={r.asz_thr} off>={r.off_thr}  "
                  f"n={r.n:5d}  WR={r.wr_fade*100:5.2f}%  mean=${r.mean_fade:+.4f}  "
                  f"total=${r.sum_fade:+.2f}")

        # Save full sweep
        rdf.to_csv(CACHE / "_f2_flow_direction_sweep.csv", index=False)
        print(f"\nsaved -> {CACHE / '_f2_flow_direction_sweep.csv'}")

    # Quick raw stats
    print()
    print("=" * 80)
    print("Unfiltered (entire universe) WR check")
    print("=" * 80)
    print(f"  follow WR: {df.won_follow.mean()*100:.2f}%  mean PnL: ${df.pnl_follow.mean():+.4f}")
    print(f"  fade   WR: {df.won_fade.mean()*100:.2f}%  mean PnL: ${df.pnl_fade.mean():+.4f}")

    # Strong-flow only
    strong = df[df.flow_imbalance_5s.abs() >= 0.3]
    print(f"\n  Strong flow (|imbalance|>=0.3): n={len(strong):,}")
    print(f"    follow WR: {strong.won_follow.mean()*100:.2f}%  mean PnL: ${strong.pnl_follow.mean():+.4f}")
    print(f"    fade   WR: {strong.won_fade.mean()*100:.2f}%  mean PnL: ${strong.pnl_fade.mean():+.4f}")

    # Burst + strong-flow
    burst = strong[strong.n_trades_5s >= 50]
    print(f"\n  Trade burst (n>=50) + strong flow: n={len(burst):,}")
    print(f"    follow WR: {burst.won_follow.mean()*100:.2f}%  mean PnL: ${burst.pnl_follow.mean():+.4f}  "
          f"total=${burst.pnl_follow.sum():+.2f}")
    print(f"    fade   WR: {burst.won_fade.mean()*100:.2f}%  mean PnL: ${burst.pnl_fade.mean():+.4f}  "
          f"total=${burst.pnl_fade.sum():+.2f}")


if __name__ == "__main__":
    main()
