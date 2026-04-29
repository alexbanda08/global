"""
polymarket_rank_ic.py — Rank-IC time series for Polymarket signals.

Adapted from AlphaPurify FactorAnalyzer.calc_stats_for_horizon (L849-1000):
group by trade-date cross-section, compute Spearman rank correlation between
factor and forward outcome, output a daily IC series + summary stats.

Why this matters for Polymarket UpDown:
  • IC drift detection — first concrete trigger to retire a signal
  • IC IR = mean/std — single number to compare alt-signals (execution-independent)
  • IC autocorr — how persistent is the signal? Informs refit cadence

Cross-section definition: markets sharing the same window_start_date (UTC day).
Within each cross-section, we compute Spearman(factor, outcome_up) per (asset, timeframe).

Outputs:
  results/polymarket/rank_ic_series.csv   — daily IC time series
  results/polymarket/rank_ic_summary.csv  — per-(factor, asset, tf) summary stats
  reports/polymarket/02_analysis/POLYMARKET_RANK_IC.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
ASSETS = ["btc", "eth", "sol"]
TIMEFRAMES = ["5m", "15m"]

# Factors to evaluate
FACTORS = [
    "ret_5m",            # primary signal
    "ret_15m",
    "ret_1h",
    "smart_minus_retail",
    "book_skew",
    "taker_ratio",
    "oi_delta_5m",
    "ls_top_sum",
]

MIN_CROSS_SECTION = 5  # min markets per (date, asset, tf) bucket to compute IC


def load_all_features() -> pd.DataFrame:
    """Load and concat all asset feature CSVs."""
    frames = []
    for asset in ASSETS:
        df = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_features_v3.csv")
        df["asset"] = asset
        frames.append(df)
    feats = pd.concat(frames, ignore_index=True)
    feats["window_start_date"] = pd.to_datetime(feats["window_start_unix"], unit="s", utc=True).dt.date
    return feats


def compute_cross_section_ic(
    feats: pd.DataFrame,
    factor: str,
    target: str = "outcome_up",
    min_n: int = MIN_CROSS_SECTION,
) -> pd.DataFrame:
    """
    For each (window_start_date, asset, timeframe) cross-section, compute Spearman
    rank correlation between factor and target.

    Returns DataFrame with columns: date, asset, timeframe, n, ic, factor.
    """
    rows = []
    grouped = feats.groupby(["window_start_date", "asset", "timeframe"])
    for (date, asset, tf), g in grouped:
        x = g[factor].to_numpy()
        y = g[target].to_numpy()
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() < min_n:
            continue
        x_, y_ = x[mask], y[mask]
        if np.unique(x_).size < 2 or np.unique(y_).size < 2:
            continue
        rho, _ = spearmanr(x_, y_)
        if not np.isfinite(rho):
            continue
        rows.append({
            "date": date, "asset": asset, "timeframe": tf,
            "n": int(mask.sum()), "ic": float(rho), "factor": factor,
        })
    return pd.DataFrame(rows)


def summarize_ic(ic_series: pd.DataFrame) -> dict:
    """
    Summary stats across the daily IC series for one (factor, asset, tf) cell.
        mean_ic, std_ic, ic_ir (= mean/std, the IC information ratio),
        ic_autocorr (lag-1 Pearson on the IC series),
        signed_t_stat (one-sample t test that mean IC ≠ 0),
        pct_positive, n_dates, mean_n_per_xs.
    """
    if ic_series.empty:
        return {k: float("nan") for k in
                ["mean_ic","std_ic","ic_ir","ic_autocorr","t_stat","pct_positive"]} | {
                    "n_dates": 0, "mean_n_per_xs": float("nan")}
    ic_sorted = ic_series.sort_values("date")
    ic = ic_sorted["ic"].to_numpy()
    n = ic.size
    mean_ic = float(ic.mean())
    std_ic = float(ic.std(ddof=1)) if n > 1 else float("nan")
    ic_ir = mean_ic / std_ic if std_ic and std_ic > 0 else float("nan")
    t_stat = mean_ic / (std_ic / np.sqrt(n)) if std_ic and std_ic > 0 and n > 1 else float("nan")
    if n >= 2:
        ic1 = ic[:-1]; ic2 = ic[1:]
        if np.std(ic1) > 0 and np.std(ic2) > 0:
            ic_autocorr = float(np.corrcoef(ic1, ic2)[0, 1])
        else:
            ic_autocorr = float("nan")
    else:
        ic_autocorr = float("nan")
    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "ic_ir": ic_ir,
        "ic_autocorr": ic_autocorr,
        "t_stat": float(t_stat) if np.isfinite(t_stat) else float("nan"),
        "pct_positive": float((ic > 0).mean()),
        "n_dates": int(n),
        "mean_n_per_xs": float(ic_sorted["n"].mean()),
    }


def main():
    print("Loading features...")
    feats = load_all_features()
    print(f"  {len(feats)} markets across {feats.window_start_date.nunique()} dates")

    all_series = []
    summary_rows = []

    for factor in FACTORS:
        if factor not in feats.columns:
            print(f"  [skip] {factor} not in features")
            continue
        print(f"Computing IC for factor={factor}...")
        ic_df = compute_cross_section_ic(feats, factor)
        if ic_df.empty:
            print(f"  no usable cross-sections for {factor}")
            continue
        all_series.append(ic_df)

        # Summary stats per (asset, tf), plus the "ALL" cell aggregating across asset
        for tf in TIMEFRAMES:
            for asset in ["ALL"] + ASSETS:
                if asset == "ALL":
                    cell = ic_df[ic_df.timeframe == tf]
                else:
                    cell = ic_df[(ic_df.timeframe == tf) & (ic_df.asset == asset)]
                summ = summarize_ic(cell)
                summ.update({"factor": factor, "asset": asset, "timeframe": tf})
                summary_rows.append(summ)
                print(f"  {factor:24s} {tf} {asset:3s} | "
                      f"mean_IC={summ['mean_ic']:+.4f} IR={summ['ic_ir']:+.2f} "
                      f"autocorr={summ['ic_autocorr']:+.2f} t={summ['t_stat']:+.2f} "
                      f"pos%={summ['pct_positive']*100:.0f} n_dates={summ['n_dates']}")

    series_csv = HERE / "results" / "polymarket" / "rank_ic_series.csv"
    summary_csv = HERE / "results" / "polymarket" / "rank_ic_summary.csv"
    out_md = HERE / "reports" / "polymarket" / "02_analysis" / "POLYMARKET_RANK_IC.md"
    series_csv.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    if all_series:
        full_series = pd.concat(all_series, ignore_index=True)
        full_series.to_csv(series_csv, index=False)
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(summary_csv, index=False)

    md = ["# Polymarket Rank-IC Analysis\n"]
    md.append(f"Cross-section definition: markets grouped by (window_start_date, asset, timeframe). "
              f"IC = Spearman rank correlation between factor and `outcome_up`. "
              f"Min {MIN_CROSS_SECTION} markets per cross-section.\n")
    md.append(f"**Universe:** {len(feats)} markets across {feats.window_start_date.nunique()} dates "
              f"(BTC + ETH + SOL × {TIMEFRAMES}).\n")

    md.append("\n## Summary — top factors by |IC IR| (timeframe-stratified)\n")
    for tf in TIMEFRAMES:
        md.append(f"\n### Timeframe {tf}\n")
        md.append("| Factor | Asset | Mean IC | IR | Autocorr | t-stat | %positive | n_dates |")
        md.append("|---|---|---|---|---|---|---|---|")
        sub = summary[summary.timeframe == tf].copy()
        sub["abs_ir"] = sub["ic_ir"].abs()
        sub = sub.sort_values("abs_ir", ascending=False, na_position="last").drop(columns="abs_ir")
        for _, r in sub.head(20).iterrows():
            md.append(
                f"| {r['factor']} | {r['asset']} | {r['mean_ic']:+.4f} | "
                f"{r['ic_ir']:+.2f} | {r['ic_autocorr']:+.2f} | {r['t_stat']:+.2f} | "
                f"{r['pct_positive']*100:.0f}% | {int(r['n_dates'])} |"
            )

    md.append("\n## Interpretation guide\n")
    md.append("- **Mean IC** — average rank correlation per cross-section. Positive = factor predicts outcome.")
    md.append("- **IR (Information Ratio)** = mean_IC / std_IC. Higher = more consistent. >0.5 is decent for daily.")
    md.append("- **Autocorr** = lag-1 corr of the IC series. >0.3 = persistent (signal durable). <0 = noisy/regime-flipping.")
    md.append("- **t-stat** = mean_IC / (std_IC / sqrt(n_dates)). |t| > 2 suggests IC ≠ 0 statistically.")
    md.append("- **%positive** — share of dates with positive IC. Should agree directionally with mean IC.\n")
    md.append("\n## How to use this for the live strategy\n")
    md.append("- **Drift trigger:** if rolling 14-day mean IC drops below half its all-time level for `ret_5m`, retire/refit.")
    md.append("- **Alt-signal screen:** any factor with |IR| > existing `ret_5m` IR is a candidate for the next experiment.")
    md.append("- **Refit cadence:** if autocorr > 0.5, refit weekly; if < 0.2, refit daily or move on.\n")

    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote:\n  {series_csv}\n  {summary_csv}\n  {out_md}")


if __name__ == "__main__":
    main()
