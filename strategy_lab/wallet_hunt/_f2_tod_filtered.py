"""Test: trade-flow trigger + F2 time-of-day filter on broad 21d universe.

F2's preferred hours (UTC):
  00, 22, 23  → super-strong (lift > 2.5x)
  07-10        → strong (lift > 1.5x)

F2 avoids:
  03, 12, 15, 18-21  → 0% firing

Hypothesis: applying the trigger ONLY during these hours flips the
broad-universe result from -$14k to positive.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from cyclops.validate.permutation import permutation_test  # noqa: E402
from cyclops.validate.bootstrap import bootstrap_mean_ci  # noqa: E402
from cyclops.validate.walkforward import walkforward_test  # noqa: E402

# F2's preferred firing hours (UTC) — top 8 from analysis
F2_HOURS_TIGHT = {22, 23, 0}                        # super-strong
F2_HOURS_BROAD = {22, 23, 0, 1, 9, 10, 4, 5, 7}     # all with lift > 1.5x
F2_HOURS_INVERSE = {3, 12, 15, 18, 19, 20, 21}      # always-skip

BROAD_CSV = "strategy_lab/f2_replica/_results/f2_v2_broad_full.csv"


def annotate_time(df):
    df = df.copy()
    df["ts"] = pd.to_datetime(df.fire_ts_us, unit="us", utc=True)
    df["hour_utc"] = df.ts.dt.hour
    df["weekday"] = df.ts.dt.weekday
    df["ws_s"] = df.slot_start_s.astype(int)
    return df


def evaluate(df, label, hour_set=None, drop_hours=None):
    sub = df.copy()
    if hour_set is not None:
        sub = sub[sub.hour_utc.isin(hour_set)]
    if drop_hours is not None:
        sub = sub[~sub.hour_utc.isin(drop_hours)]
    if len(sub) < 50:
        print(f"  [{label}] insufficient n={len(sub)}")
        return None
    wr = sub.won.mean()
    mean_pnl = sub.pnl_usd.mean()
    total = sub.pnl_usd.sum()
    print(f"\n[{label}]")
    print(f"  n = {len(sub):,}")
    print(f"  WR = {wr*100:.2f}%")
    print(f"  mean PnL = ${mean_pnl:+.4f}  ({len(sub)} trades)")
    print(f"  total PnL = ${total:+.2f}  (=$25 stake: ${total*25:+.2f})")
    daily = sub.groupby(pd.to_datetime(sub.ws_s, unit="s").dt.date).agg(
        n=("won", "size"), wr=("won", "mean"), pnl=("pnl_usd", "sum")
    )
    print("  daily breakdown:")
    print(daily.to_string(index=True))
    return sub


def gates(label, sub):
    if sub is None or len(sub) < 50:
        return
    sub2 = sub.copy()
    sub2["outcome_truth"] = sub2.winner if "winner" in sub2.columns else sub2.outcome_truth
    sub2["stake_usd"] = sub2.stake_usd if "stake_usd" in sub2.columns else 1.0
    p = permutation_test(sub2, n_permutations=3000, seed=42)
    b = bootstrap_mean_ci(sub2, n_boot=10000, seed=42)
    wf = walkforward_test(sub2, train_days=5, test_days=2)
    print(f"\n  [{label}] validation gates:")
    print(f"    G3 perm:  p={p['p_value']:.4f}  -> {'PASS' if p['p_value'] < 0.05 else 'FAIL'}")
    print(f"    G4 boot:  CI [{b['ci_lower']:+.4f} .. {b['ci_upper']:+.4f}]  "
          f"-> {'PASS' if b['ci_lower'] > 0 else 'FAIL'}")
    print(f"    G2 walk:  {wf['n_positive']}/{wf['n_windows']} pos  -> {wf['verdict']}")


def main():
    df = pd.read_csv(BROAD_CSV)
    df = annotate_time(df)
    print(f"loaded broad universe: n={len(df):,} fires")
    print(f"  date range: {pd.to_datetime(df.ws_s, unit='s').min()} -> "
          f"{pd.to_datetime(df.ws_s, unit='s').max()}")

    # Variant 1: ALL HOURS (control)
    s1 = evaluate(df, "1_all_hours")
    gates("1_all_hours", s1)

    # Variant 2: F2 TIGHT hours only (22-00 UTC)
    s2 = evaluate(df, "2_tight_hours_22_to_00", hour_set=F2_HOURS_TIGHT)
    gates("2_tight_hours_22_to_00", s2)

    # Variant 3: F2 BROAD hours (top-lift list)
    s3 = evaluate(df, "3_broad_hours", hour_set=F2_HOURS_BROAD)
    gates("3_broad_hours", s3)

    # Variant 4: Exclude F2-avoided hours
    s4 = evaluate(df, "4_exclude_us_hours", drop_hours=F2_HOURS_INVERSE)
    gates("4_exclude_us_hours", s4)

    # Variant 5: Tightest = F2 TIGHT + only flow>0.3 + only Wed/Fri
    tight5 = df.copy()
    tight5 = tight5[tight5.hour_utc.isin(F2_HOURS_TIGHT)]
    tight5 = tight5[tight5.flow_imbalance_5s.abs() >= 0.3]
    tight5 = tight5[tight5.weekday.isin({2, 4})]   # Wed=2, Fri=4
    s5 = evaluate(tight5, "5_super_tight")
    gates("5_super_tight", s5)


if __name__ == "__main__":
    main()
