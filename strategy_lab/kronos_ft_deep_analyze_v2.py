"""
kronos_ft_deep_analyze_v2 — Phase 2 CPU analysis of the BTC sniff CSV.

Follow-up investigation after phase 1 revealed:
  - 5m edge is REAL overall (57%, CI [52.8, 61.5])
  - But monthly breakdown shows decay: Jan 60%, Feb 59%, Mar 54%
  - Edge concentrates in low-vol periods

This script answers:
  1. WEEKLY breakdown — is the March collapse uniform or concentrated?
  2. CONFIDENCE THRESHOLDING — does filtering to top-|pred_ret| windows
     recover a stable edge even in March?
  3. INTRADAY — UTC-hour buckets and weekday edge (session effect?)
  4. PRED-MAGNITUDE vs ACCURACY — the decile ladder (actionable for live trading)

Usage:
  py strategy_lab/kronos_ft_deep_analyze_v2.py \
      --csv strategy_lab/results/kronos/ft_sniff_BTCUSDT_5m_3y_polymarket_short.csv \
      --out strategy_lab/reports/KRONOS_FT_DEEP_BTC_V2.md
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
BOOTSTRAP_N = 5000


def load(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv, parse_dates=["ctx_end"])
    df = df.sort_values(["ctx_end", "bar"]).reset_index(drop=True)
    df["pred_dir"] = np.sign(df["pred_ret"]).astype(int)
    df["actual_dir"] = np.sign(df["actual_ret"]).astype(int)
    df["correct"] = (df["pred_dir"] == df["actual_dir"]).astype(int)
    df["push"] = ((df["actual_ret"] == 0) | (df["pred_ret"] == 0)).astype(int)
    df["abs_pred"] = df["pred_ret"].abs()
    return df


def weekly(df: pd.DataFrame, bar: int) -> pd.DataFrame:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    sub["week"] = sub["ctx_end"].dt.to_period("W-MON").astype(str)
    g = sub.groupby("week").agg(n=("correct", "size"), acc=("correct", "mean")).round(4)
    return g


def decile_ladder(df: pd.DataFrame, bar: int) -> pd.DataFrame:
    """For each confidence decile, show n and accuracy.
    Interpretation: if the top decile has >60% accuracy, we have a
    tradable signal even if the overall edge is only ~57%."""
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    sub["decile"] = pd.qcut(sub["abs_pred"], q=10, labels=[f"D{i+1}" for i in range(10)])
    g = sub.groupby("decile", observed=True).agg(
        n=("correct", "size"),
        acc=("correct", "mean"),
        avg_abs_pred_pct=("abs_pred", lambda s: s.mean() * 100),
    ).round(4)
    return g


def top_k_threshold(df: pd.DataFrame, bar: int, top_frac: float) -> dict:
    """Selective trading: only take the top X% highest-confidence predictions."""
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    cutoff = sub["abs_pred"].quantile(1 - top_frac)
    sub_hi = sub[sub["abs_pred"] >= cutoff]
    if len(sub_hi) == 0:
        return {"frac": top_frac, "n": 0}
    acc = sub_hi["correct"].mean()
    # Bootstrap CI
    x = sub_hi["correct"].to_numpy()
    idx = RNG.integers(0, len(x), size=(BOOTSTRAP_N, len(x)))
    means = x[idx].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return {
        "frac": top_frac,
        "n": int(len(sub_hi)),
        "acc": round(float(acc), 4),
        "acc_ci95": [round(float(lo), 4), round(float(hi), 4)],
        "avg_abs_pred_pct": round(float(sub_hi["abs_pred"].mean() * 100), 4),
    }


def threshold_by_month(df: pd.DataFrame, bar: int, top_frac: float) -> pd.DataFrame:
    """Does the selective-trading accuracy stay stable across months?"""
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    sub["month"] = sub["ctx_end"].dt.to_period("M").astype(str)
    cutoff = sub["abs_pred"].quantile(1 - top_frac)
    sub_hi = sub[sub["abs_pred"] >= cutoff]
    g = sub_hi.groupby("month").agg(n=("correct", "size"), acc=("correct", "mean")).round(4)
    return g


def hour_of_day(df: pd.DataFrame, bar: int) -> pd.DataFrame:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    sub["hour"] = sub["ctx_end"].dt.hour
    g = sub.groupby("hour").agg(n=("correct", "size"), acc=("correct", "mean")).round(4)
    return g


def day_of_week(df: pd.DataFrame, bar: int) -> pd.DataFrame:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    sub["dow"] = sub["ctx_end"].dt.day_name()
    # Preserve Mon..Sun order
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    g = sub.groupby("dow").agg(n=("correct", "size"), acc=("correct", "mean"))
    g = g.reindex([d for d in order if d in g.index]).round(4)
    return g


def render(data: dict, out: Path) -> None:
    L = ["# Kronos FT — BTC Deep Analysis V2 (Stability + Confidence)", ""]
    L.append(f"Source: `{data['csv']}`  ")
    L.append(f"Bootstrap samples: {BOOTSTRAP_N}")
    L.append("")

    # Section 1: Weekly stability
    L.append("## 1. Weekly accuracy — 5m horizon")
    L.append("")
    L.append("Is March's collapse uniform or one bad week?")
    L.append("")
    L.append("| Week | n | Acc |")
    L.append("|---|---|---|")
    for week, row in data["weekly_5m"].iterrows():
        L.append(f"| {week} | {int(row['n'])} | {row['acc']:.3f} |")
    L.append("")

    # Section 2: Decile ladder
    L.append("## 2. Confidence-decile ladder — 5m")
    L.append("")
    L.append("Accuracy sorted by prediction magnitude. A rising staircase = "
             "selective trading is viable.")
    L.append("")
    L.append("| Decile | n | Acc | Avg \\|pred\\| % |")
    L.append("|---|---|---|---|")
    for decile, row in data["decile_5m"].iterrows():
        L.append(f"| {decile} | {int(row['n'])} | {row['acc']:.3f} | {row['avg_abs_pred_pct']:.4f} |")
    L.append("")

    # Section 3: Top-fraction thresholds
    L.append("## 3. Selective-trading thresholds — 5m")
    L.append("")
    L.append("Only bet on the top X% highest-|pred_ret| forecasts.")
    L.append("")
    L.append("| Top fraction | n | Acc | 95% CI | Avg \\|pred\\| % |")
    L.append("|---|---|---|---|---|")
    for t in data["thresholds_5m"]:
        if t.get("n", 0) == 0:
            continue
        L.append(f"| {t['frac']:.0%} | {t['n']} | {t['acc']:.3f} | "
                 f"[{t['acc_ci95'][0]:.3f}, {t['acc_ci95'][1]:.3f}] | "
                 f"{t['avg_abs_pred_pct']:.4f} |")
    L.append("")

    # Section 4: Threshold by month — is selective trading ALSO stable?
    L.append("## 4. Does selective trading survive the March drop?")
    L.append("")
    L.append("Top 25% by month (only the most confident predictions):")
    L.append("")
    L.append("| Month | n | Acc |")
    L.append("|---|---|---|")
    for month, row in data["top25_by_month_5m"].iterrows():
        L.append(f"| {month} | {int(row['n'])} | {row['acc']:.3f} |")
    L.append("")
    L.append("Top 10% by month (elite confidence):")
    L.append("")
    L.append("| Month | n | Acc |")
    L.append("|---|---|---|")
    for month, row in data["top10_by_month_5m"].iterrows():
        L.append(f"| {month} | {int(row['n'])} | {row['acc']:.3f} |")
    L.append("")

    # Section 5: Hour-of-day
    L.append("## 5. Accuracy by UTC hour — 5m")
    L.append("")
    L.append("| Hour (UTC) | n | Acc |")
    L.append("|---|---|---|")
    for hour, row in data["hour_5m"].iterrows():
        L.append(f"| {int(hour):02d} | {int(row['n'])} | {row['acc']:.3f} |")
    L.append("")

    # Section 6: Day-of-week
    L.append("## 6. Accuracy by weekday — 5m")
    L.append("")
    L.append("| Day | n | Acc |")
    L.append("|---|---|---|")
    for dow, row in data["dow_5m"].iterrows():
        L.append(f"| {dow} | {int(row['n'])} | {row['acc']:.3f} |")
    L.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = load(Path(args.csv))
    BAR = 1  # 5m

    data = {
        "csv": args.csv,
        "weekly_5m": weekly(df, BAR),
        "decile_5m": decile_ladder(df, BAR),
        "thresholds_5m": [
            top_k_threshold(df, BAR, frac) for frac in [0.50, 0.25, 0.10, 0.05]
        ],
        "top25_by_month_5m": threshold_by_month(df, BAR, 0.25),
        "top10_by_month_5m": threshold_by_month(df, BAR, 0.10),
        "hour_5m": hour_of_day(df, BAR),
        "dow_5m": day_of_week(df, BAR),
    }

    # Print highlights
    print("=== Selective-trading thresholds (5m) ===")
    for t in data["thresholds_5m"]:
        if t.get("n", 0) > 0:
            print(f"  top {t['frac']:.0%}: n={t['n']}, acc={t['acc']:.3f}, "
                  f"CI=[{t['acc_ci95'][0]:.3f}, {t['acc_ci95'][1]:.3f}]")

    render(data, Path(args.out))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
