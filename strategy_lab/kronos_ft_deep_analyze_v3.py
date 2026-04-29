"""
kronos_ft_deep_analyze_v3 — Combined filter strategy analysis.

V2 found three independent edge dimensions on the 5m BTC signal:
  A. Confidence (|pred_ret|) — top 25% hits 63%
  B. Hour-of-day         — some UTC hours hit 65-78%, others <50%
  C. Day-of-week         — Saturday is 48%, Sun-Fri all >55%

This script cascades the filters to see what's left and whether the
combined signal is (a) profitable enough to trade, (b) has enough
samples to not be overfitting noise.

Deliverable: a concrete tradable spec — "bet when X, Y, Z" — with
projected live bet frequency.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
BOOTSTRAP_N = 5000

# Hours with >= 58% acc from V2 analysis (10-hour whitelist)
GOOD_HOURS = {8, 10, 11, 12, 14, 17, 18, 19, 20, 22}
# Days where model is NOT inverted
GOOD_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Sunday"}


def load(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv, parse_dates=["ctx_end"])
    df = df.sort_values(["ctx_end", "bar"]).reset_index(drop=True)
    df["pred_dir"] = np.sign(df["pred_ret"]).astype(int)
    df["actual_dir"] = np.sign(df["actual_ret"]).astype(int)
    df["correct"] = (df["pred_dir"] == df["actual_dir"]).astype(int)
    df["push"] = ((df["actual_ret"] == 0) | (df["pred_ret"] == 0)).astype(int)
    df["abs_pred"] = df["pred_ret"].abs()
    df["hour"] = df["ctx_end"].dt.hour
    df["dow"] = df["ctx_end"].dt.day_name()
    df["month"] = df["ctx_end"].dt.to_period("M").astype(str)
    return df


def bootstrap_ci(x: np.ndarray, n: int = BOOTSTRAP_N):
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    idx = RNG.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return (float(x.mean()), float(lo), float(hi))


def ev(acc: float, payout: float = 0.95) -> float:
    return acc * payout - (1 - acc)


def apply_filters(df: pd.DataFrame, bar: int, use_conf: bool, use_hour: bool,
                  use_dow: bool, conf_frac: float = 0.25) -> pd.DataFrame:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    if use_conf:
        cutoff = sub["abs_pred"].quantile(1 - conf_frac)
        sub = sub[sub["abs_pred"] >= cutoff]
    if use_hour:
        sub = sub[sub["hour"].isin(GOOD_HOURS)]
    if use_dow:
        sub = sub[sub["dow"].isin(GOOD_DAYS)]
    return sub


def summarize_filter(df: pd.DataFrame, name: str, bar: int, use_conf: bool,
                     use_hour: bool, use_dow: bool, conf_frac: float = 0.25) -> dict:
    sub = apply_filters(df, bar, use_conf, use_hour, use_dow, conf_frac)
    n = len(sub)
    if n == 0:
        return {"name": name, "n": 0}
    acc, lo, hi = bootstrap_ci(sub["correct"].to_numpy())
    return {
        "name": name,
        "n": int(n),
        "acc": round(acc, 4),
        "acc_ci95": [round(lo, 4), round(hi, 4)],
        "ev_95payout": round(ev(acc, 0.95), 4),
        "ev_90payout": round(ev(acc, 0.90), 4),
    }


def monthly_stability(df: pd.DataFrame, bar: int, use_conf: bool,
                      use_hour: bool, use_dow: bool) -> pd.DataFrame:
    sub = apply_filters(df, bar, use_conf, use_hour, use_dow)
    g = sub.groupby("month").agg(n=("correct", "size"), acc=("correct", "mean")).round(4)
    return g


def render(data: dict, out: Path) -> None:
    L = ["# Kronos FT — BTC Combined-Filter Strategy (V3)", ""]
    L.append(f"Source: `{data['csv']}`")
    L.append(f"Test window: 2026-01-08 → 2026-03-31 (82 days, ~6 forecasts/day sampled)")
    L.append(f"Good hours (UTC): {sorted(GOOD_HOURS)}")
    L.append(f"Good days: Monday-Friday + Sunday (exclude Saturday)")
    L.append("")

    L.append("## Filter cascade — accuracy vs sample count")
    L.append("")
    L.append("| Strategy | n | Acc | 95% CI | EV@95% payout | EV@90% payout |")
    L.append("|---|---|---|---|---|---|")
    for r in data["filters"]:
        if r.get("n", 0) == 0:
            continue
        L.append(f"| {r['name']} | {r['n']} | {r['acc']:.3f} | "
                 f"[{r['acc_ci95'][0]:.3f}, {r['acc_ci95'][1]:.3f}] | "
                 f"{r['ev_95payout']:+.3f} | {r['ev_90payout']:+.3f} |")
    L.append("")
    L.append("EV computed as: acc × payout − (1 − acc). Positive EV = profitable.")
    L.append("")

    L.append("## Monthly stability — Combined filter (conf + hour + dow)")
    L.append("")
    L.append("| Month | n | Acc |")
    L.append("|---|---|---|")
    for m, row in data["monthly_combined"].iterrows():
        L.append(f"| {m} | {int(row['n'])} | {row['acc']:.3f} |")
    L.append("")

    L.append("## Monthly stability — Hour + DOW filter only (no confidence threshold)")
    L.append("")
    L.append("| Month | n | Acc |")
    L.append("|---|---|---|")
    for m, row in data["monthly_hour_dow"].iterrows():
        L.append(f"| {m} | {int(row['n'])} | {row['acc']:.3f} |")
    L.append("")

    L.append("## Live-trading projection")
    L.append("")
    L.append("Test slice sampled 500 windows from 82 days = ~6 forecasts/day.")
    L.append("If live model runs every 5m, that's 288 forecasts/day (48× more).")
    L.append("")
    L.append("| Strategy | Sampled bets | Per-day bets | Per-day bets (live 5m) |")
    L.append("|---|---|---|---|")
    for r in data["filters"]:
        if r.get("n", 0) == 0:
            continue
        per_day_sampled = r["n"] / 82.0
        per_day_live = per_day_sampled * 48
        L.append(f"| {r['name']} | {r['n']} | {per_day_sampled:.2f} | {per_day_live:.1f} |")
    L.append("")

    L.append("## Recommended trading spec")
    L.append("")
    rec = next((r for r in data["filters"] if r["name"] == "conf25 + hour + dow"), None)
    if rec and rec.get("n", 0) > 0:
        per_day_live = rec["n"] / 82.0 * 48
        L.append(f"**Entry:** 5m BTC forecast on finetuned Kronos →")
        L.append(f"   IF `hour_utc ∈ {sorted(GOOD_HOURS)}`")
        L.append(f"   AND `weekday ≠ Saturday`")
        L.append(f"   AND `|pred_ret|` in top 25% of recent predictions")
        L.append(f"   THEN bet `sign(pred_ret)` on the 5-min Polymarket up/down market.")
        L.append("")
        L.append(f"**Expected accuracy:** {rec['acc']:.1%} (95% CI [{rec['acc_ci95'][0]:.1%}, {rec['acc_ci95'][1]:.1%}])")
        L.append(f"**Expected EV/bet (5% spread):** {rec['ev_95payout']:+.3f} per $1 staked")
        L.append(f"**Expected live bet rate:** ~{per_day_live:.0f} bets/day")
        L.append(f"**Caveat:** based on {rec['n']} test samples. CI is wide — monitor first 100 live bets carefully before scaling.")
    L.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = load(Path(args.csv))
    BAR = 1

    filters = [
        summarize_filter(df, "baseline (no filter)", BAR, False, False, False),
        summarize_filter(df, "conf top 25%", BAR, True, False, False),
        summarize_filter(df, "hour only", BAR, False, True, False),
        summarize_filter(df, "dow only", BAR, False, False, True),
        summarize_filter(df, "hour + dow", BAR, False, True, True),
        summarize_filter(df, "conf25 + hour", BAR, True, True, False),
        summarize_filter(df, "conf25 + dow", BAR, True, False, True),
        summarize_filter(df, "conf25 + hour + dow", BAR, True, True, True),
        summarize_filter(df, "conf top 10% + hour + dow", BAR, True, True, True, conf_frac=0.10),
    ]

    data = {
        "csv": args.csv,
        "filters": filters,
        "monthly_combined": monthly_stability(df, BAR, True, True, True),
        "monthly_hour_dow": monthly_stability(df, BAR, False, True, True),
    }

    # Print highlights
    print("=== Filter cascade ===")
    for r in filters:
        if r.get("n", 0) > 0:
            print(f"  {r['name']:<28} n={r['n']:>4}  acc={r['acc']:.3f}  "
                  f"CI=[{r['acc_ci95'][0]:.3f}, {r['acc_ci95'][1]:.3f}]")

    render(data, Path(args.out))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
