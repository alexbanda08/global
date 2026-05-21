"""G2: rolling-window walkforward stability.

The strategy has no learned parameters (only fixed thresholds), so we can't
do a "train threshold → test PnL" loop. Instead we measure stability: split
the 21-day window into rolling test buckets and check how many have positive
mean PnL.

Default schedule (spec §7): 5d train + 2d test, sliding. With 21 days we
expect ~8 test windows. Pass if ≥6 of the windows have positive mean PnL.
We do NOT change strategy parameters between windows — this is purely a
stability/regime test on a fixed strategy.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


def walkforward_test(
    fired: pd.DataFrame,
    train_days: int = 5,
    test_days: int = 2,
    pass_threshold_frac: float = 6 / 8,
) -> Dict:
    """Compute test-window mean PnL across a rolling schedule.

    Returns a dict of per-window stats + an overall pass/fail verdict.
    `pass_threshold_frac` is the minimum FRACTION of windows that must show
    positive mean PnL to PASS (spec default ≈ 6/8 = 75%).
    """
    if fired.empty:
        return {"n_windows": 0, "n_positive": 0, "verdict": "no_trades"}

    df = fired.copy()
    df["dt_utc"] = pd.to_datetime(df["ws_s"], unit="s", utc=True)
    df["day_idx"] = (df["ws_s"] // 86_400).astype("int64")
    day_min = int(df["day_idx"].min())
    day_max = int(df["day_idx"].max())
    total_days = day_max - day_min + 1
    period = train_days + test_days

    windows: List[Dict] = []
    cur = day_min + train_days  # first test-window start
    while cur + test_days - 1 <= day_max:
        test_lo, test_hi = cur, cur + test_days - 1
        sub = df[(df["day_idx"] >= test_lo) & (df["day_idx"] <= test_hi)]
        if not sub.empty:
            windows.append({
                "test_start_day": int(test_lo),
                "test_end_day": int(test_hi),
                "test_start_iso": str(pd.Timestamp(test_lo * 86_400, unit="s", tz="UTC")),
                "n_trades": int(len(sub)),
                "mean_pnl": float(sub["pnl_usd"].mean()),
                "wr": float(sub["won"].mean()) if "won" in sub.columns else None,
                "total_pnl": float(sub["pnl_usd"].sum()),
            })
        cur += test_days

    n_windows = len(windows)
    n_positive = sum(1 for w in windows if w["mean_pnl"] > 0)
    frac_positive = (n_positive / n_windows) if n_windows else float("nan")
    verdict = (
        "PASS" if n_windows >= 4 and frac_positive >= pass_threshold_frac
        else ("FAIL" if n_windows >= 4 else "insufficient_windows")
    )

    return {
        "total_days": int(total_days),
        "train_days": int(train_days),
        "test_days": int(test_days),
        "pass_threshold_frac": float(pass_threshold_frac),
        "n_windows": int(n_windows),
        "n_positive": int(n_positive),
        "frac_positive": float(frac_positive) if n_windows else float("nan"),
        "verdict": verdict,
        "windows": windows,
    }


def main():
    ap = argparse.ArgumentParser(description="Cyclops G2 walkforward stability")
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--train-days", type=int, default=5)
    ap.add_argument("--test-days", type=int, default=2)
    ap.add_argument("--pass-frac", type=float, default=6 / 8)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    fired = df[df["fired"] == True].copy()
    result = walkforward_test(fired, train_days=args.train_days,
                              test_days=args.test_days,
                              pass_threshold_frac=args.pass_frac)
    result["csv"] = str(args.csv)

    out_path = args.out or args.csv.with_suffix(".walkforward.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(f"[walk]  n_windows={result['n_windows']}  "
          f"n_positive={result['n_positive']}  "
          f"frac={result['frac_positive']:.3f}  -> [{result['verdict']}]")
    for w in result["windows"]:
        marker = "+" if w["mean_pnl"] > 0 else "-"
        print(f"  [{marker}] day {w['test_start_day']}-{w['test_end_day']}  "
              f"n={w['n_trades']:3d}  mean=${w['mean_pnl']:+.4f}  "
              f"total=${w['total_pnl']:+.2f}")
    print(f"[walk]  wrote {out_path}")


if __name__ == "__main__":
    main()
