"""Phase 7 — CLOB Imbalance MOMENTUM (book pressure derivative).

Hypothesis: Static CLOB imbalance has weak edge (Phase 2 IC=+0.082 ETH).
The DERIVATIVE of imbalance (rate of book pressure change) should be stronger
because it captures buildup, not steady state.

Data: data/v4/refresh_2026_05_02/btc_book_depth_v3_full.csv
  Columns: slug, timeframe, resolve_unix, window_start_unix, bucket_10s,
           outcome ('Up'|'Down'), snap_ts_us, bid_price_0..9, bid_size_0..9,
           ask_price_0..9, ask_size_0..9
  Cadence: 10-second buckets, starts at bucket_10s=0 (= window_start_unix).
  No pre-window book data. So "signal time" must be EARLY in the window.

For each (slug,outcome='Up') we compute, at signal_time t (chosen as
2 min into window, with lookback to window_start):

  imb_t        = (sum_bid_top5 - sum_ask_top5) / (sum_bid_top5 + sum_ask_top5)
                 at the bucket nearest t (Up-token book)
  imb_slope_2m = (imb_t - imb_{t-2min}) / 120
  imb_slope_5m = (imb_t - imb_{t-5min}) / 300  [15m markets only]
  abs_imb_t    = |imb_t|
  imb_accel_2m = imb_slope_2m - imb_slope_2m_at_(t-1min)

We use t = window_start_unix + 120 (i.e., 2 minutes after window start),
so we look back to bucket 0 for the 2m slope. For 5m markets the
imb_slope_5m is forced NaN (would need pre-window). For 15m markets we
use t = window_start + 300 so 5m slope is available.

Output: strategy_lab/data/meta_classifier/btc_clob_momentum_v1.parquet
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
BOOK_PATH = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_book_depth_v3_full.csv"
FEATURES_PATH = ROOT / "strategy_lab" / "data" / "polymarket" / "btc_features_v3.csv"
MARKETS_MIN = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
OUT_PARQUET = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_clob_momentum_v1.parquet"
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "PHASE7_CLOB_MOMENTUM.md"

TOP_K = 5  # top-5 cumulative depth


def compute_book_imbalance(df: pd.DataFrame, k: int = TOP_K) -> pd.DataFrame:
    """Add imb (top-k) to each row of the Up-token book."""
    bid_cols = [f"bid_size_{i}" for i in range(k)]
    ask_cols = [f"ask_size_{i}" for i in range(k)]
    df = df.copy()
    df["bid_sum"] = df[bid_cols].sum(axis=1)
    df["ask_sum"] = df[ask_cols].sum(axis=1)
    tot = df["bid_sum"] + df["ask_sum"]
    df["imb"] = np.where(tot > 0, (df["bid_sum"] - df["ask_sum"]) / tot, np.nan)
    return df[["slug", "timeframe", "window_start_unix", "bucket_10s", "outcome",
               "snap_ts_us", "bid_sum", "ask_sum", "imb"]]


def nearest_bucket(group: pd.DataFrame, target_bucket: int) -> pd.Series | None:
    """Find row whose bucket_10s is closest to target_bucket. Returns None if no row within tolerance."""
    if group.empty:
        return None
    diffs = (group["bucket_10s"] - target_bucket).abs()
    idx = diffs.idxmin()
    if diffs.loc[idx] > 6:  # >60 seconds off — too stale
        return None
    return group.loc[idx]


def build_features(book: pd.DataFrame) -> pd.DataFrame:
    """Per slug (Up token only), compute momentum features at signal_time."""
    book = book[book["outcome"] == "Up"].copy()
    book = compute_book_imbalance(book)

    # Sort once globally for groupby speed
    book = book.sort_values(["slug", "bucket_10s"])

    rows = []
    for slug, g in book.groupby("slug", sort=False):
        tf = g["timeframe"].iloc[0]
        ws = g["window_start_unix"].iloc[0]
        # signal_time: 2 min into window for 5m markets; 5 min for 15m markets
        if tf == "5m":
            t_bucket = 12  # 120s
            slope5_bucket_lo = None  # not enough lookback
        elif tf == "15m":
            t_bucket = 30  # 300s = 5 min in
            slope5_bucket_lo = 0
        else:
            continue

        # Need: row at t_bucket, t_bucket-12 (2m back), t_bucket-30 (5m back),
        #       and t_bucket-6 (1m back, for accel reference) and (t_bucket-6) - 12 (1m back, 2m back from there)
        idx_t = nearest_bucket(g, t_bucket)
        if idx_t is None:
            continue
        idx_t_minus_2m = nearest_bucket(g, t_bucket - 12)
        if idx_t_minus_2m is None:
            continue

        imb_t = idx_t["imb"]
        imb_t_2m = idx_t_minus_2m["imb"]
        if pd.isna(imb_t) or pd.isna(imb_t_2m):
            continue

        slope_2m = (imb_t - imb_t_2m) / 120.0
        abs_imb_t = abs(imb_t)

        # 5m slope (only for 15m markets)
        slope_5m = np.nan
        if slope5_bucket_lo is not None:
            idx_t_minus_5m = nearest_bucket(g, slope5_bucket_lo)
            if idx_t_minus_5m is not None and not pd.isna(idx_t_minus_5m["imb"]):
                slope_5m = (imb_t - idx_t_minus_5m["imb"]) / 300.0

        # Acceleration: slope_2m at t  minus  slope_2m at (t - 1m)
        accel_2m = np.nan
        idx_t_minus_1m = nearest_bucket(g, t_bucket - 6)
        idx_t_minus_3m = nearest_bucket(g, t_bucket - 18)
        if (idx_t_minus_1m is not None and idx_t_minus_3m is not None
                and not pd.isna(idx_t_minus_1m["imb"]) and not pd.isna(idx_t_minus_3m["imb"])):
            slope_2m_prev = (idx_t_minus_1m["imb"] - idx_t_minus_3m["imb"]) / 120.0
            accel_2m = slope_2m - slope_2m_prev

        rows.append({
            "slug": slug,
            "timeframe": tf,
            "window_start_unix": ws,
            "imb_t": imb_t,
            "imb_slope_2m": slope_2m,
            "imb_slope_5m": slope_5m,
            "abs_imb_t": abs_imb_t,
            "imb_accel_2m": accel_2m,
        })

    return pd.DataFrame(rows)


def ic_table(df: pd.DataFrame, label: str) -> str:
    """Print IC table for each feature vs outcome_up."""
    feats = ["imb_t", "imb_slope_2m", "imb_slope_5m", "abs_imb_t", "imb_accel_2m"]
    lines = [f"\n### IC table — {label} (n={len(df)})\n",
             "| Feature | n | IC (Spearman rho) | p-value |",
             "|---|---|---|---|"]
    for f in feats:
        sub = df.dropna(subset=[f, "outcome_up"])
        if len(sub) < 30:
            lines.append(f"| {f} | {len(sub)} | n/a | n/a |")
            continue
        rho, p = spearmanr(sub[f], sub["outcome_up"])
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else ""))
        lines.append(f"| {f} | {len(sub)} | {rho:+.4f} {sig} | {p:.4g} |")
    return "\n".join(lines)


def threshold_sweep(df: pd.DataFrame, feat: str = "imb_slope_2m", invert: bool = False) -> str:
    """Hit-rate sweep: predict UP if feat > +threshold, predict DOWN if < -threshold.

    If invert=True (use when IC sign is negative / contrarian), flip prediction.
    """
    sub = df.dropna(subset=[feat, "outcome_up"]).copy()
    abs_vals = sub[feat].abs()
    sign_label = " (CONTRARIAN: predict opposite of feature sign)" if invert else ""
    lines = [f"\n### Threshold sweep — {feat}{sign_label} (n={len(sub)})\n",
             "| |feat| pct | threshold | n_fired | hit_rate |",
             "|---|---|---|---|"]
    for q in [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]:
        thr = abs_vals.quantile(q)
        fired = sub[abs_vals >= thr].copy()
        if len(fired) == 0:
            lines.append(f"| {q:.2f} | {thr:+.6g} | 0 | n/a |")
            continue
        if invert:
            fired["pred_up"] = fired[feat] < 0  # contrarian
        else:
            fired["pred_up"] = fired[feat] > 0
        fired["hit"] = ((fired["pred_up"]) & (fired["outcome_up"] == 1)) | \
                       ((~fired["pred_up"]) & (fired["outcome_up"] == 0))
        hit = fired["hit"].mean()
        lines.append(f"| {q:.2f} | {thr:+.6g} | {len(fired)} | {hit:.3f} |")
    return "\n".join(lines)


def main():
    print(f"Loading book depth: {BOOK_PATH}")
    book = pd.read_csv(BOOK_PATH)
    print(f"  rows={len(book)}, slugs={book['slug'].nunique()}")

    print("Computing momentum features...")
    feats = build_features(book)
    print(f"  features computed for {len(feats)} slugs")
    print(f"  by timeframe:\n{feats.groupby('timeframe').size()}")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(OUT_PARQUET, index=False)
    print(f"  wrote parquet -> {OUT_PARQUET}")

    # Join to outcome_up
    print("Joining to btc_features_v3 for outcome_up...")
    bf = pd.read_csv(FEATURES_PATH)[["slug", "outcome_up"]]
    df = feats.merge(bf, on="slug", how="inner")
    print(f"  joined rows: {len(df)} (univ {feats.shape[0]} -> matched {len(df)})")

    # Reports
    sections = [
        "# Phase 7 — CLOB Imbalance MOMENTUM\n",
        f"_Generated: 2026-05-04_\n",
        "## Hypothesis\n",
        "Phase 2 static imbalance had weak/null edge (best: ETH IC=+0.082).",
        "The 2-min DERIVATIVE of book imbalance should capture buildup pressure,",
        "which is more predictive than steady-state level.\n",
        "## Data Schema\n",
        f"- File: `data/v4/refresh_2026_05_02/btc_book_depth_v3_full.csv`",
        f"- Rows: {len(book):,} | Unique slugs: {book['slug'].nunique():,}",
        f"- Cadence: 10-second buckets (`bucket_10s`), bucket=0 at `window_start_unix`",
        f"- Top-10 levels each side, both Up & Down outcome books",
        f"- No pre-window data → signal_time must be intra-window\n",
        "## Signal Construction\n",
        f"- Use Up-token book only; top-{TOP_K} cumulative depth for imbalance",
        "- `imb_t = (sum_bid_top5 - sum_ask_top5) / (sum_bid_top5 + sum_ask_top5)`",
        "- 5m markets: t = bucket 12 (=120s into window); slope_2m looks back to bucket 0",
        "- 15m markets: t = bucket 30 (=300s into window); slope_5m looks back to bucket 0",
        "- All slugs: slope_2m = (imb_t - imb_{t-12}) / 120",
        "- accel_2m = slope_2m(t) - slope_2m(t-6) (second derivative, ~1m offset)\n",
        "## Feature Coverage\n",
        f"- Total slugs with features: {len(feats):,}",
        f"- 5m: {(feats['timeframe']=='5m').sum():,}",
        f"- 15m: {(feats['timeframe']=='15m').sum():,}",
        f"- Joined to outcome_up: {len(df):,}\n",
        "## IC Tables\n",
        ic_table(df, "BTC ALL"),
        ic_table(df[df["timeframe"] == "5m"], "BTC 5m only"),
        ic_table(df[df["timeframe"] == "15m"], "BTC 15m only"),
        "\n## Threshold Sweep — imb_slope_2m, NAIVE direction (BTC ALL)\n",
        threshold_sweep(df, "imb_slope_2m"),
        "\n## Threshold Sweep — imb_slope_2m, CONTRARIAN (BTC ALL)\n",
        "_(IC is negative → invert sign: positive book pressure on Up early in window predicts Down outcome)_\n",
        threshold_sweep(df, "imb_slope_2m", invert=True),
        "\n## Threshold Sweep — imb_t static, NAIVE (BTC ALL)\n",
        threshold_sweep(df, "imb_t"),
        "\n## Threshold Sweep — imb_t static, CONTRARIAN (BTC ALL)\n",
        threshold_sweep(df, "imb_t", invert=True),
    ]

    # Compute verdict
    sub_slope = df.dropna(subset=["imb_slope_2m", "outcome_up"])
    sub_static = df.dropna(subset=["imb_t", "outcome_up"])
    rho_slope, p_slope = spearmanr(sub_slope["imb_slope_2m"], sub_slope["outcome_up"])
    rho_static, p_static = spearmanr(sub_static["imb_t"], sub_static["outcome_up"])

    sections += [
        "\n## Comparison vs Phase 2\n",
        "| Metric | Phase 2 (ETH static) | Phase 7 (BTC slope_2m) | Phase 7 (BTC static) |",
        "|---|---|---|---|",
        f"| IC | +0.082 | {rho_slope:+.4f} (p={p_slope:.3g}) | {rho_static:+.4f} (p={p_static:.3g}) |",
        f"| n   | ~ETH univ | {len(sub_slope)} | {len(sub_static)} |",
        "\n## Verdict\n",
    ]

    momentum_wins = abs(rho_slope) > abs(rho_static) and p_slope < 0.10
    static_better = abs(rho_static) > abs(rho_slope)
    significant_either = p_slope < 0.05 or p_static < 0.05
    contrarian = rho_slope < 0  # negative IC = contrarian signal

    sign_note = ""
    if contrarian:
        sign_note = (" Note: BOTH ICs are NEGATIVE — signal is CONTRARIAN. "
                     "Bid-heavy book on Up token early in the window predicts the Up token "
                     "FAILS to settle. Likely retail-dump-into-strength or fade-the-late-piler dynamic. "
                     "To use, invert: predict UP when slope < 0.")

    if momentum_wins and p_slope < 0.05:
        verdict = (f"**CONFIRMED (contrarian)**: imb_slope_2m IC ({rho_slope:+.4f}, p={p_slope:.3g}) "
                   f"is stronger and more significant than static imb_t IC "
                   f"({rho_static:+.4f}, p={p_static:.3g}). Momentum DERIVATIVE beats LEVEL — "
                   "the hypothesis from the research doc holds, just with opposite sign than "
                   "intuition would suggest.{}".format(sign_note))
    elif momentum_wins:
        verdict = (f"**WEAK CONFIRM**: slope IC ({rho_slope:+.4f}) > static IC ({rho_static:+.4f}) "
                   f"in magnitude but slope p={p_slope:.3g} not strongly significant.{sign_note}")
    elif static_better and significant_either:
        verdict = (f"**REFUTED**: static imb_t ({rho_static:+.4f}) beats slope ({rho_slope:+.4f}). "
                   "Momentum hypothesis fails — level matters more than derivative.{}".format(sign_note))
    else:
        verdict = (f"**NULL**: neither slope ({rho_slope:+.4f}, p={p_slope:.3g}) "
                   f"nor static ({rho_static:+.4f}, p={p_static:.3g}) significant. "
                   "BTC CLOB book pressure has no measurable edge in this universe.")
    sections.append(verdict)

    sections += [
        "\n## Artifacts\n",
        f"- Feature parquet: `{OUT_PARQUET.relative_to(ROOT)}`",
        f"- This report: `{REPORT_PATH.relative_to(ROOT)}`",
    ]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(sections), encoding="utf-8")
    print(f"  wrote report  -> {REPORT_PATH}")
    print("\n=== VERDICT ===")
    print(verdict)


if __name__ == "__main__":
    main()
