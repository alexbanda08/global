"""
kronos_ft_vs_naive — Is Kronos actually smarter than 3-line baselines?

The risk: a 400 MB fine-tuned transformer may just be re-deriving
"bet sign of last bar's return" (momentum). If so, we should trade
momentum directly and save the GPU.

For each Kronos-sampled window (bar==1, 5m horizon), we compute the same
actual_ret target and four predictions:

  1. Kronos      — the transformer's pred_ret
  2. Momentum    — sign(last 5m return) = sign(c0 - prior_close)
  3. Reversion   — -sign(last 5m return) (bet the opposite of momentum)
  4. Hour-bias   — always bet the historical positive-return bias of
                    that UTC hour, computed on JAN only and applied to all

All four are measured:
  a) overall on the full 500-window test slice
  b) within the hour+dow filter window (the strategy we'd actually trade)

If Kronos beats momentum+reversion+hour-bias in the filter window by a
wide margin, the transformer is adding real value.
If momentum hits 65%+ in the filter window, Kronos is redundant and
we can trade the cheap baseline instead.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
BOOTSTRAP_N = 5000

GOOD_HOURS = {8, 10, 11, 12, 14, 17, 18, 19, 20, 22}
GOOD_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Sunday"}


def load_kronos(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv, parse_dates=["ctx_end"])
    df = df[df["bar"] == 1].copy()
    df["actual_dir"] = np.sign(df["actual_ret"]).astype(int)
    df["pred_dir_kronos"] = np.sign(df["pred_ret"]).astype(int)
    df["push"] = ((df["actual_ret"] == 0) | (df["pred_ret"] == 0)).astype(int)
    df["hour"] = df["ctx_end"].dt.hour
    df["dow"] = df["ctx_end"].dt.day_name()
    df["month"] = df["ctx_end"].dt.to_period("M").astype(str)
    return df


def load_raw(csv: Path) -> pd.DataFrame:
    raw = pd.read_csv(csv, parse_dates=["timestamps"])
    raw = raw.sort_values("timestamps").reset_index(drop=True)
    raw = raw.set_index("timestamps")
    return raw


def add_baselines(df: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """
    For each row in df (ctx_end is the close-time of the context window,
    c0 is the close price at ctx_end), compute:
      - prev_close  : raw close at ctx_end - 5min
      - last_ret    : c0 / prev_close - 1
      - momentum_dir: sign(last_ret)
      - reversion_dir: -sign(last_ret)
    """
    # Build a lookup: ctx_end - 5min -> close
    lookup = raw["close"]
    ctx_prev = df["ctx_end"] - pd.Timedelta(minutes=5)
    prev_closes = lookup.reindex(ctx_prev).values
    df["prev_close"] = prev_closes
    df["last_ret"] = df["c0"] / df["prev_close"] - 1
    df["pred_dir_momentum"] = np.sign(df["last_ret"]).astype(int)
    df["pred_dir_reversion"] = -df["pred_dir_momentum"]
    return df


def add_hourbias(df: pd.DataFrame, train_months: list) -> pd.DataFrame:
    """
    Fit a "always bet that hour's historical positive-return sign" model
    using only the training months. Apply it everywhere.
    """
    train = df[df["month"].isin(train_months) & (df["push"] == 0)].copy()
    # For each hour, mean of actual_dir (>0 means historically more up-bars)
    hour_bias = train.groupby("hour")["actual_dir"].mean()
    # Predict +1 where hour_bias >= 0 else -1
    sign_map = hour_bias.apply(lambda x: 1 if x >= 0 else -1).to_dict()
    df["pred_dir_hourbias"] = df["hour"].map(sign_map).fillna(1).astype(int)
    return df


def bootstrap_ci(x: np.ndarray):
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    idx = RNG.integers(0, len(x), size=(BOOTSTRAP_N, len(x)))
    means = x[idx].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return (float(x.mean()), float(lo), float(hi))


def score(df: pd.DataFrame, pred_col: str) -> dict:
    sub = df[(df["push"] == 0) & (~df["prev_close"].isna())].copy()
    if len(sub) == 0:
        return {"n": 0}
    correct = (sub[pred_col] == sub["actual_dir"]).astype(int).to_numpy()
    acc, lo, hi = bootstrap_ci(correct)
    return {"n": int(len(sub)), "acc": round(acc, 4),
            "ci95": [round(lo, 4), round(hi, 4)]}


def score_filtered(df: pd.DataFrame, pred_col: str) -> dict:
    sub = df[(df["push"] == 0) & (~df["prev_close"].isna()) &
             (df["hour"].isin(GOOD_HOURS)) & (df["dow"].isin(GOOD_DAYS))].copy()
    if len(sub) == 0:
        return {"n": 0}
    correct = (sub[pred_col] == sub["actual_dir"]).astype(int).to_numpy()
    acc, lo, hi = bootstrap_ci(correct)
    return {"n": int(len(sub)), "acc": round(acc, 4),
            "ci95": [round(lo, 4), round(hi, 4)]}


def render(data: dict, out: Path) -> None:
    L = ["# Kronos vs Naive Baselines — BTC 5m", ""]
    L.append("Same 500 test windows. Measures whether the 400 MB fine-tuned "
             "Kronos actually beats 3-line baselines.")
    L.append("")
    L.append("## Overall (unfiltered)")
    L.append("")
    L.append("| Predictor | n | Acc | 95% CI |")
    L.append("|---|---|---|---|")
    for name, r in data["overall"].items():
        if r.get("n", 0) == 0:
            continue
        L.append(f"| {name} | {r['n']} | {r['acc']:.3f} | "
                 f"[{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}] |")
    L.append("")

    L.append("## In the hour+dow filter window (the actual trading universe)")
    L.append("")
    L.append(f"Hours: {sorted(GOOD_HOURS)} | Exclude: Saturday")
    L.append("")
    L.append("| Predictor | n | Acc | 95% CI |")
    L.append("|---|---|---|---|")
    for name, r in data["filtered"].items():
        if r.get("n", 0) == 0:
            continue
        L.append(f"| {name} | {r['n']} | {r['acc']:.3f} | "
                 f"[{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}] |")
    L.append("")

    L.append("## Interpretation")
    L.append("")
    k = data["filtered"].get("Kronos", {})
    m = data["filtered"].get("Momentum", {})
    if k.get("acc") and m.get("acc"):
        diff = (k["acc"] - m["acc"]) * 100
        L.append(f"- Kronos - Momentum (filtered) = **{diff:+.1f}pp**")
        if diff > 5:
            L.append("- **Kronos adds substantial value over naive momentum.**")
        elif diff > 2:
            L.append("- Kronos adds some value; marginal case.")
        else:
            L.append("- **Kronos is ~equivalent to momentum in the filter window.** "
                    "Trading momentum directly may be more robust + free.")
    L.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kronos-csv", required=True)
    ap.add_argument("--raw-csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = load_kronos(Path(args.kronos_csv))
    raw = load_raw(Path(args.raw_csv))

    df = add_baselines(df, raw)
    df = add_hourbias(df, train_months=["2026-01"])

    predictors = {
        "Kronos": "pred_dir_kronos",
        "Momentum": "pred_dir_momentum",
        "Reversion": "pred_dir_reversion",
        "HourBias (fit-Jan)": "pred_dir_hourbias",
    }

    overall = {name: score(df, col) for name, col in predictors.items()}
    filtered = {name: score_filtered(df, col) for name, col in predictors.items()}

    data = {"overall": overall, "filtered": filtered}

    print("=== Overall (unfiltered) ===")
    for name, r in overall.items():
        if r.get("n", 0) > 0:
            print(f"  {name:<22} n={r['n']:>3}  acc={r['acc']:.3f}  CI=[{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}]")
    print("\n=== Hour+DOW filter window ===")
    for name, r in filtered.items():
        if r.get("n", 0) > 0:
            print(f"  {name:<22} n={r['n']:>3}  acc={r['acc']:.3f}  CI=[{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}]")

    render(data, Path(args.out))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
