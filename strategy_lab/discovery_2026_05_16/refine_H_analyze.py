"""
Analyze refine_H_*.parquet results.
Identify best (tf, anchor, horizon, thr) cells. For each candidate, run permutation +
walk-forward + per-asset breakdown.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

DIR = Path(__file__).resolve().parent

def load_all() -> pd.DataFrame:
    frames = []
    for f in sorted(DIR.glob("refine_H_*_anchor*.parquet")):
        df = pd.read_parquet(f)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main():
    df = load_all()
    if len(df) == 0:
        print("no data yet")
        return
    print(f"total fires across all anchors: {len(df):,}")
    print(f"unique (tf, anchor): {df[['tf','anchor_off_s']].drop_duplicates().shape[0]}")
    print()

    # ===== Aggregate sweep =====
    agg = (
        df.groupby(["tf","anchor_off_s","horizon_s","thr"])
          .agg(n=("won","size"), hit=("won","mean"), pnl=("pnl","sum"),
               pnl_per_trade=("pnl","mean"), median_vwap=("vwap","median"))
          .round(4).reset_index()
    )
    agg.to_csv(DIR / "refine_H_aggregate.csv", index=False)

    print("=== TOP 20 by total PnL (n >= 200) ===")
    top = agg[agg["n"] >= 200].sort_values("pnl", ascending=False).head(20)
    print(top.to_string(index=False))
    print()
    print("=== TOP 20 by pnl_per_trade (n >= 200) ===")
    top_pt = agg[agg["n"] >= 200].sort_values("pnl_per_trade", ascending=False).head(20)
    print(top_pt.to_string(index=False))
    print()
    print("=== Per-asset for the top-PnL config ===")
    if len(top):
        b = top.iloc[0]
        tf_, anc_, hor_, thr_ = b.tf, b.anchor_off_s, b.horizon_s, b.thr
        sub = df[(df.tf==tf_) & (df.anchor_off_s==anc_) & (df.horizon_s==hor_) & (df.thr==thr_)]
        per_asset = (
            sub.groupby("asset")
               .agg(n=("won","size"), hit=("won","mean"),
                    pnl=("pnl","sum"), pnl_per_trade=("pnl","mean"))
               .round(4)
        )
        print(f"Top config: tf={tf_} anc_off={anc_}s horizon={hor_}s thr={thr_}")
        print(per_asset)

    # ===== Permutation + walk-forward on top configs =====
    print()
    print("=== Permutation + walk-forward on top 5 configs (n>=200) ===")
    np.random.seed(42)
    for i, row in top.head(5).iterrows():
        tf_, anc_, hor_, thr_ = row.tf, row.anchor_off_s, row.horizon_s, row.thr
        sub = df[(df.tf==tf_) & (df.anchor_off_s==anc_) & (df.horizon_s==hor_) & (df.thr==thr_)]
        obs_pnl = sub.pnl.sum()
        obs_hit = sub.won.mean()
        n = len(sub)
        # Permutation: random sign-flip
        pnls = []
        for _ in range(1000):
            flips = np.random.choice([1, -1], size=n)
            pnls.append((sub.pnl.values * flips).sum())
        pnls = np.array(pnls)
        p_val = (pnls >= obs_pnl).mean()

        # Walk-forward by week
        sub2 = sub.copy()
        sub2["slot_start"] = sub2.slug.str.rsplit("-", n=1).str[1].astype("int64")
        sub2["ts"] = pd.to_datetime(sub2.slot_start, unit="s", utc=True)
        sub2["week"] = sub2.ts.dt.isocalendar().week
        wk = (
            sub2.groupby("week")
                .agg(n=("won","size"), hit=("won","mean"), pnl=("pnl","sum"))
                .round(3)
        )
        print(f"\n--- tf={tf_} anc_off={anc_}s horizon={hor_}s thr={thr_} ---")
        print(f"  n={n}  hit={obs_hit:.4f}  pnl=${obs_pnl:+.2f}  perm_p_val={p_val:.4f}")
        print(f"  walk-forward by week:")
        print(wk.to_string())


if __name__ == "__main__":
    main()
