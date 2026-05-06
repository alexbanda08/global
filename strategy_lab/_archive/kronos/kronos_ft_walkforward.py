"""
kronos_ft_walkforward — Walk-forward validation of the hour/dow filter.

The risk: in V3 we picked the "good hours" AFTER seeing all 3 months of
test data. That's in-sample optimization — the 69% accuracy could be
curve-fitting to noise.

Walk-forward protocol:
  1. TRAIN ON JAN     → pick hours where acc >= 58% in Jan only
  2. TEST ON FEB      → does that same hour-set give >50%, >55% in Feb?
  3. TRAIN ON JAN+FEB → pick hours (larger sample, more stable)
  4. TEST ON MAR      → final out-of-sample check

If OOS accuracy in Feb/Mar stays >55%, the filter is REAL.
If OOS accuracy collapses to baseline (~50-53%), the filter was noise-fitting.

Same treatment for day-of-week — exclude days with acc < 50% in TRAIN,
measure accuracy on the remaining days in TEST.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
BOOTSTRAP_N = 5000
HOUR_THRESHOLD = 0.58  # Keep hours that hit this in train
DOW_THRESHOLD = 0.50   # Keep days that hit this in train


def load(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv, parse_dates=["ctx_end"])
    df = df.sort_values(["ctx_end", "bar"]).reset_index(drop=True)
    df["pred_dir"] = np.sign(df["pred_ret"]).astype(int)
    df["actual_dir"] = np.sign(df["actual_ret"]).astype(int)
    df["correct"] = (df["pred_dir"] == df["actual_dir"]).astype(int)
    df["push"] = ((df["actual_ret"] == 0) | (df["pred_ret"] == 0)).astype(int)
    df["hour"] = df["ctx_end"].dt.hour
    df["dow"] = df["ctx_end"].dt.day_name()
    df["month"] = df["ctx_end"].dt.to_period("M").astype(str)
    return df[(df["bar"] == 1) & (df["push"] == 0)].copy()


def ci_bootstrap(x: np.ndarray):
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    idx = RNG.integers(0, len(x), size=(BOOTSTRAP_N, len(x)))
    means = x[idx].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return (float(x.mean()), float(lo), float(hi))


def pick_hours(df_train: pd.DataFrame, thresh: float = HOUR_THRESHOLD) -> set:
    """Hours whose in-sample accuracy beats the threshold AND have >=5 samples."""
    g = df_train.groupby("hour").agg(n=("correct", "size"), acc=("correct", "mean"))
    keep = g[(g["acc"] >= thresh) & (g["n"] >= 5)].index.tolist()
    return set(int(h) for h in keep)


def pick_dows(df_train: pd.DataFrame, thresh: float = DOW_THRESHOLD) -> set:
    g = df_train.groupby("dow").agg(n=("correct", "size"), acc=("correct", "mean"))
    keep = g[g["acc"] >= thresh].index.tolist()
    return set(keep)


def evaluate(df_test: pd.DataFrame, hours: set, dows: set) -> dict:
    mask = df_test["hour"].isin(hours) & df_test["dow"].isin(dows)
    sub = df_test[mask]
    n = len(sub)
    if n == 0:
        return {"n": 0}
    acc, lo, hi = ci_bootstrap(sub["correct"].to_numpy())
    # Also measure the BASELINE (no filter) in the same test period for comparison
    base_acc, base_lo, base_hi = ci_bootstrap(df_test["correct"].to_numpy())
    return {
        "n": int(n),
        "n_total_available": int(len(df_test)),
        "coverage": round(n / len(df_test), 3),
        "acc_filtered": round(acc, 4),
        "acc_ci95": [round(lo, 4), round(hi, 4)],
        "baseline_acc": round(base_acc, 4),
        "baseline_ci95": [round(base_lo, 4), round(base_hi, 4)],
        "lift_pp": round((acc - base_acc) * 100, 2),
    }


def run_split(df: pd.DataFrame, train_months: list, test_months: list) -> dict:
    df_train = df[df["month"].isin(train_months)]
    df_test = df[df["month"].isin(test_months)]
    hours = pick_hours(df_train)
    dows = pick_dows(df_train)
    eval_res = evaluate(df_test, hours, dows)
    return {
        "train_months": train_months,
        "test_months": test_months,
        "train_n": int(len(df_train)),
        "test_n": int(len(df_test)),
        "picked_hours": sorted(hours),
        "picked_dows": sorted(dows),
        "eval": eval_res,
    }


def render(results: list, out: Path) -> None:
    L = ["# Kronos FT — Walk-Forward Validation of Hour/DOW Filter", ""]
    L.append("**The question:** Does the hour-whitelist we chose in V3 generalize "
             "out-of-sample, or was it curve-fit to the full 3-month test slice?")
    L.append("")
    L.append("**Protocol:** Pick hours/days using ONLY the training months. Evaluate on "
             "the held-out test months. Compare filtered accuracy to un-filtered baseline "
             "in the SAME test period.")
    L.append("")
    L.append(f"Hour keep threshold: acc ≥ {HOUR_THRESHOLD:.0%} in train, n ≥ 5")
    L.append(f"DOW keep threshold: acc ≥ {DOW_THRESHOLD:.0%} in train")
    L.append("")

    for r in results:
        train_lbl = "+".join(r["train_months"])
        test_lbl = "+".join(r["test_months"])
        L.append(f"## TRAIN on {train_lbl} → TEST on {test_lbl}")
        L.append("")
        L.append(f"- Train samples: {r['train_n']}, Test samples: {r['test_n']}")
        L.append(f"- Hours kept (from train): {r['picked_hours']}")
        L.append(f"- Days kept (from train): {r['picked_dows']}")
        L.append("")
        e = r["eval"]
        if e.get("n", 0) == 0:
            L.append("**No test samples after filter applied. Filter too strict.**")
            L.append("")
            continue
        L.append(f"**Filtered accuracy on TEST: {e['acc_filtered']:.1%} "
                 f"(95% CI [{e['acc_ci95'][0]:.1%}, {e['acc_ci95'][1]:.1%}])**")
        L.append(f"Baseline accuracy on TEST (no filter): {e['baseline_acc']:.1%} "
                 f"(95% CI [{e['baseline_ci95'][0]:.1%}, {e['baseline_ci95'][1]:.1%}])")
        L.append(f"**Lift from filter: {e['lift_pp']:+.1f}pp**")
        L.append(f"Coverage: {e['coverage']:.1%} of test samples passed filter ({e['n']}/{e['n_total_available']})")
        L.append("")

    L.append("## Verdict logic")
    L.append("")
    L.append("- Filter is REAL if OOS lift > 0pp AND OOS CI lower bound > 50%")
    L.append("- Filter is NOISE if OOS lift ≈ 0pp or negative")
    L.append("- Filter is REGIME-DEPENDENT if lift is positive on one test but negative on another")
    L.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = load(Path(args.csv))

    splits = [
        # Classic walk-forward
        (["2026-01"], ["2026-02"]),
        (["2026-01"], ["2026-03"]),
        (["2026-01"], ["2026-02", "2026-03"]),
        (["2026-01", "2026-02"], ["2026-03"]),
    ]

    results = [run_split(df, tr, te) for tr, te in splits]

    # Print highlights
    print("=== Walk-forward results ===")
    for r in results:
        train_lbl = "+".join(r["train_months"])
        test_lbl = "+".join(r["test_months"])
        e = r["eval"]
        if e.get("n", 0) == 0:
            print(f"  TRAIN {train_lbl} -> TEST {test_lbl}:  (filter dropped all samples)")
            continue
        print(f"  TRAIN {train_lbl} -> TEST {test_lbl}:  "
              f"filter acc {e['acc_filtered']:.3f} (CI [{e['acc_ci95'][0]:.3f}, {e['acc_ci95'][1]:.3f}]), "
              f"baseline {e['baseline_acc']:.3f}, lift {e['lift_pp']:+.1f}pp, "
              f"coverage {e['coverage']:.1%} (n={e['n']})")
        print(f"    hours: {r['picked_hours']}")

    render(results, Path(args.out))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
