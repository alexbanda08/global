"""
kronos_ft_deep_analyze — CPU-only deep analysis of the BTC sniff CSV.

Reads the per-window predictions from kronos_ft_sniff_5m.py and answers:
  1. Is the 5m edge real? (bootstrap 95% CI on direction accuracy)
  2. Is it stable across time? (monthly breakdown, rolling hit rate)
  3. Does it concentrate in specific regimes? (volatility-quartile breakdown)
  4. What's the expected value on Polymarket after slippage?
  5. How do the longer horizons actually look once we control for noise?

No GPU. No re-inference. Pure pandas/numpy on the 4500 saved rows.

Usage:
  py strategy_lab/kronos_ft_deep_analyze.py \
      --csv strategy_lab/results/kronos/ft_sniff_BTCUSDT_5m_3y_polymarket_short.csv \
      --out strategy_lab/reports/KRONOS_FT_DEEP_BTC.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HORIZONS = [("5m", 1), ("15m", 3), ("30m", 6), ("45m", 9)]
BOOTSTRAP_N = 5000
RNG = np.random.default_rng(42)


def load(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv, parse_dates=["ctx_end"])
    df = df.sort_values(["ctx_end", "bar"]).reset_index(drop=True)
    df["pred_dir"] = np.sign(df["pred_ret"]).astype(int)
    df["actual_dir"] = np.sign(df["actual_ret"]).astype(int)
    df["correct"] = (df["pred_dir"] == df["actual_dir"]).astype(int)
    # Guard against zero-return rows: treat 0 as a "push" (exclude from dir-acc)
    df["push"] = ((df["actual_ret"] == 0) | (df["pred_ret"] == 0)).astype(int)
    return df


def bootstrap_ci(x: np.ndarray, n: int = BOOTSTRAP_N, ci: float = 0.95) -> tuple[float, float, float]:
    """Return (mean, lo, hi) bootstrap CI."""
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    idx = RNG.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    lo = np.quantile(means, (1 - ci) / 2)
    hi = np.quantile(means, 1 - (1 - ci) / 2)
    return (float(x.mean()), float(lo), float(hi))


def summarize_horizon(df: pd.DataFrame, label: str, bar: int) -> dict:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    n = len(sub)
    if n == 0:
        return {"horizon": label, "n": 0}
    acc_mean, acc_lo, acc_hi = bootstrap_ci(sub["correct"].to_numpy())
    # Majority-bet baseline = frequency of the more common actual direction
    pos_rate = (sub["actual_dir"] > 0).mean()
    majority = max(pos_rate, 1 - pos_rate)
    edge_pp = (acc_mean - majority) * 100.0
    edge_lo = (acc_lo - majority) * 100.0
    edge_hi = (acc_hi - majority) * 100.0
    pearson = float(np.corrcoef(sub["pred_ret"], sub["actual_ret"])[0, 1])
    mae = float((sub["actual_ret"] - sub["pred_ret"]).abs().mean())
    return {
        "horizon": label,
        "n": int(n),
        "acc": round(acc_mean, 4),
        "acc_ci95": [round(acc_lo, 4), round(acc_hi, 4)],
        "majority_baseline": round(majority, 4),
        "edge_pp": round(edge_pp, 2),
        "edge_pp_ci95": [round(edge_lo, 2), round(edge_hi, 2)],
        "pearson": round(pearson, 4),
        "mae_pct": round(mae * 100, 4),
        "verdict": (
            "REAL" if edge_lo > 0 and acc_lo > 0.5
            else ("MARGINAL" if edge_mean_positive(edge_lo, edge_hi) else "NOISE")
        ),
    }


def edge_mean_positive(lo: float, hi: float) -> bool:
    return (lo + hi) / 2 > 0


def monthly_breakdown(df: pd.DataFrame, bar: int) -> pd.DataFrame:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    sub["month"] = sub["ctx_end"].dt.to_period("M").astype(str)
    g = sub.groupby("month").agg(
        n=("correct", "size"),
        acc=("correct", "mean"),
        pos_rate=("actual_dir", lambda s: (s > 0).mean()),
    )
    g["majority"] = g["pos_rate"].apply(lambda p: max(p, 1 - p))
    g["edge_pp"] = (g["acc"] - g["majority"]) * 100
    return g.round(4)


def rolling_acc(df: pd.DataFrame, bar: int, window: int = 100) -> pd.DataFrame:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy().reset_index(drop=True)
    sub["roll_acc"] = sub["correct"].rolling(window).mean()
    return sub[["ctx_end", "roll_acc"]].dropna()


def vol_quartile_breakdown(df: pd.DataFrame, bar: int) -> pd.DataFrame:
    sub = df[(df["bar"] == bar) & (df["push"] == 0)].copy()
    # Proxy realized vol by |actual_ret| quartile at this horizon
    sub["vol_q"] = pd.qcut(sub["actual_ret"].abs(), q=4, labels=["Q1_low", "Q2", "Q3", "Q4_high"])
    g = sub.groupby("vol_q", observed=True).agg(
        n=("correct", "size"),
        acc=("correct", "mean"),
    ).round(4)
    return g


def ev_polymarket(acc: float, payout: float = 0.95) -> float:
    """EV per $1 stake on a binary market. payout=0.95 means 5% spread/fee.
    Win: +payout. Lose: -1. EV = acc*payout - (1-acc)*1."""
    return acc * payout - (1 - acc)


def render(report_data: dict, out: Path) -> None:
    lines = ["# Kronos Fine-Tune — BTC Deep Sniff Analysis", ""]
    lines.append(f"Source: `{report_data['source_csv']}`")
    lines.append(f"Generated: {pd.Timestamp.now().isoformat()}")
    lines.append(f"Bootstrap samples: {BOOTSTRAP_N}")
    lines.append("")
    lines.append("## Verdict by horizon")
    lines.append("")
    lines.append("| Horizon | n | Acc | 95% CI | Majority | Edge (pp) | Edge CI | Pearson | MAE% | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for h in report_data["horizons"]:
        if h.get("n", 0) == 0:
            continue
        lines.append(
            f"| **{h['horizon']}** | {h['n']} | {h['acc']:.3f} | "
            f"[{h['acc_ci95'][0]:.3f}, {h['acc_ci95'][1]:.3f}] | "
            f"{h['majority_baseline']:.3f} | **{h['edge_pp']:+.1f}** | "
            f"[{h['edge_pp_ci95'][0]:+.1f}, {h['edge_pp_ci95'][1]:+.1f}] | "
            f"{h['pearson']:+.3f} | {h['mae_pct']:.3f} | **{h['verdict']}** |"
        )
    lines.append("")
    lines.append("**Decision rule:** Verdict = REAL when the lower 95% CI on edge > 0 AND accuracy CI lower bound > 50%.")
    lines.append("")

    # Monthly breakdown for each horizon
    for h_label, bar in HORIZONS:
        lines.append(f"## Monthly breakdown — {h_label}")
        lines.append("")
        m = report_data["monthly"][h_label]
        lines.append("| Month | n | Acc | Majority | Edge (pp) |")
        lines.append("|---|---|---|---|---|")
        for month, row in m.iterrows():
            lines.append(f"| {month} | {int(row['n'])} | {row['acc']:.3f} | "
                         f"{row['majority']:.3f} | {row['edge_pp']:+.1f} |")
        lines.append("")

    # Vol-quartile breakdown for 5m (the interesting horizon)
    lines.append("## Volatility regime — 5m horizon (|actual_ret| quartile)")
    lines.append("")
    vq = report_data["vol_5m"]
    lines.append("| Quartile | n | Acc |")
    lines.append("|---|---|---|")
    for qname, row in vq.iterrows():
        lines.append(f"| {qname} | {int(row['n'])} | {row['acc']:.3f} |")
    lines.append("")

    # Expected value on Polymarket
    lines.append("## Polymarket EV estimate (5m)")
    lines.append("")
    lines.append("| Payout assumption | EV per $1 |")
    lines.append("|---|---|")
    h5 = next((h for h in report_data["horizons"] if h["horizon"] == "5m"), None)
    if h5:
        acc = h5["acc"]
        for p in [1.00, 0.97, 0.95, 0.92, 0.90]:
            ev = ev_polymarket(acc, p)
            lines.append(f"| {p:.2f} (spread {(1-p)*100:.0f}%) | {ev:+.4f} |")
    lines.append("")
    lines.append("EV > 0 after the worst plausible spread = strategy is viable.")
    lines.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    csv_path = Path(args.csv)
    df = load(csv_path)

    horizons = [summarize_horizon(df, label, bar) for label, bar in HORIZONS]
    monthly = {label: monthly_breakdown(df, bar) for label, bar in HORIZONS}
    vol_5m = vol_quartile_breakdown(df, 1)

    report = {
        "source_csv": str(csv_path),
        "horizons": horizons,
        "monthly": monthly,
        "vol_5m": vol_5m,
    }

    # Print quick summary to stdout
    print(json.dumps({"horizons": horizons}, indent=2, default=str))

    render(report, Path(args.out))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
