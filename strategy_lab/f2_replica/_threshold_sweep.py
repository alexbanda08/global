"""Sweep F2 trigger thresholds on full 21d data to find profitable variants.

Inputs: f2_full_21d.csv (already generated)
Tightens thresholds and re-computes WR / PnL.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

CSV = Path("strategy_lab/f2_replica/_results/f2_full_21d.csv")


def main():
    df = pd.read_csv(CSV)
    print(f"loaded {len(df)} fires (full 21d run)")
    print(f"raw stats: WR={df.won.mean()*100:.2f}%  total=${df.pnl_usd.sum():+.2f}  "
          f"mean=${df.pnl_usd.mean():+.4f}")
    print()

    # Per-direction quick check
    for d, sub in df.groupby("direction"):
        print(f"  {d:5s}: n={len(sub):4d}  WR={sub.won.mean()*100:5.2f}%  "
              f"mean=${sub.pnl_usd.mean():+.4f}  total=${sub.pnl_usd.sum():+.2f}")
    print()

    # Threshold sensitivity sweep
    df["abs_ret_bp"] = df["binance_ret_60s"].abs() * 10000

    print("=" * 100)
    print("Sweep tighter triggers")
    print("=" * 100)
    print(f"{'ret_bp':>7s} {'asz':>5s} {'sa':>6s} {'offset':>6s}  "
          f"{'n':>5s}  {'WR%':>6s}  {'mean':>8s}  {'total':>8s}  "
          f"{'br_WR':>6s}  {'edge':>6s}")
    print("-" * 100)

    results = []
    for ret_bp in (2, 3, 5, 7, 10, 15):
        for asz_thr in (200, 500, 1000, 2000):
            for sa_thr in (1.005, 1.010, 1.020, 1.030):
                for off_thr in (240, 250, 260, 270):
                    mask = (
                        (df.abs_ret_bp >= ret_bp)
                        & (df.max_asz >= asz_thr)
                        & (df.sum_asks >= sa_thr)
                        & (df.offset_s >= off_thr)
                    )
                    sub = df[mask]
                    if len(sub) < 20:
                        continue
                    wr = sub.won.mean()
                    mean_entry = sub.entry_px.mean()
                    bk_wr = mean_entry  # break-even = entry price (for $1 stake)
                    edge_pp = (wr - bk_wr) * 100
                    rec = {
                        "ret_bp": ret_bp, "asz": asz_thr, "sa": sa_thr,
                        "off": off_thr, "n": len(sub), "wr": wr,
                        "mean": float(sub.pnl_usd.mean()),
                        "total": float(sub.pnl_usd.sum()),
                        "bk_wr": float(mean_entry),
                        "edge_pp": float(edge_pp),
                    }
                    results.append(rec)
                    if edge_pp > 3 or rec["mean"] > 0:
                        print(f"  {ret_bp:>7d} {asz_thr:>5d} {sa_thr:>6.3f} "
                              f"{off_thr:>6d}  {len(sub):>5d}  "
                              f"{wr*100:>5.2f}%  ${rec['mean']:+.4f}  "
                              f"${rec['total']:+.2f}  "
                              f"{bk_wr*100:>5.2f}%  {edge_pp:+.2f}pp")

    print()
    ranked = sorted(results, key=lambda r: r["total"], reverse=True)
    print("Top 10 by total PnL:")
    for r in ranked[:10]:
        print(f"  ret>={r['ret_bp']}bp asz>={r['asz']} sa>={r['sa']} off>={r['off']}  "
              f"n={r['n']:4d}  WR={r['wr']*100:5.2f}%  "
              f"mean=${r['mean']:+.4f}  total=${r['total']:+.2f}  "
              f"edge={r['edge_pp']:+.2f}pp")

    print()
    ranked_wr = sorted(results, key=lambda r: r["wr"], reverse=True)
    print("Top 10 by WR (n>=30):")
    for r in ranked_wr[:15]:
        if r["n"] < 30: continue
        print(f"  ret>={r['ret_bp']}bp asz>={r['asz']} sa>={r['sa']} off>={r['off']}  "
              f"n={r['n']:4d}  WR={r['wr']*100:5.2f}%  "
              f"mean=${r['mean']:+.4f}  total=${r['total']:+.2f}")


if __name__ == "__main__":
    main()
