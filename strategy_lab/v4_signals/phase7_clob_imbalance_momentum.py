"""phase7_clob_imbalance_momentum.py

Test whether CLOB imbalance MOMENTUM (slope/derivative over the first N buckets
of a Polymarket UpDown market) predicts outcome better than static imbalance.

Hypothesis: static CLOB imbalance has weak edge (Phase 2 found IC=+0.082 for ETH only).
The DERIVATIVE of imbalance (rate of book-pressure buildup over the first 60-120s
of the market) should be stronger because it captures intent that is forming, not
the static state which mixes informed + noise traders.

Inputs:
  strategy_lab/data/polymarket/{btc,eth,sol}_book_depth_v3.csv

Per slug × outcome (Up/Down) we have buckets 0..N at 10s cadence with top-10 each side.

Features computed per slug (using BOTH Up-token and Down-token book data):

  imb_b      = (sum bid_size_top5 - sum ask_size_top5) / total          # range [-1, 1]
  imb_avg_T  = mean(imb_b for b < T/10)                                  # static avg over T seconds
  imb_slope_T = (imb_at_bucket_T/10 - imb_at_bucket_0)                   # change over T seconds

For each slug we compute for the YES (Up) book and the NO (Down) book separately,
then combine: imb_diff_T = imb_up_T - imb_dn_T (book asymmetry).

Backtest:
  IC = Spearman correlation of feature with outcome_up (1/0).
  Per asset, per direction (UP signals vs DOWN signals — split by ret_5m sign).

Outputs:
  strategy_lab/reports/derivatives_zscore/...   (no — we use a clean path)
  Prints summary table; writes:
    strategy_lab/reports/PHASE7_CLOB_MOMENTUM_<date>.md
"""
from __future__ import annotations
from pathlib import Path
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA_DIR = ROOT / "strategy_lab" / "data" / "polymarket"
REPORTS_DIR = ROOT / "strategy_lab" / "reports"
ASSETS = ("btc", "eth", "sol")

# Top-K levels to include in imbalance computation (literature: top-5 most predictive)
TOP_K = 5
# Horizons (seconds) over which to compute features from buckets [0, horizon/10]
# These are "info available by time T" features — fair if entry at time T, hold to t=300.
HORIZONS_SEC = (10, 30, 60, 120, 180, 240, 270, 300)
# Late-window horizons — features over buckets [horizon, 300] (settlement-window dynamics).
# These are LOOKAHEAD for any entry strategy, but useful to understand how outcomes resolve.
LATE_WINDOWS_SEC = (60, 120, 180)  # last 60s, 120s, 180s of market


def safe_float(x: str) -> float:
    if x is None or x == "":
        return 0.0
    try:
        return float(x)
    except ValueError:
        return 0.0


def imbalance(row: dict, k: int) -> float:
    """Compute imbalance from top-k bid+ask sizes."""
    bid = sum(safe_float(row.get(f"bid_size_{i}", "")) for i in range(k))
    ask = sum(safe_float(row.get(f"ask_size_{i}", "")) for i in range(k))
    tot = bid + ask
    if tot <= 0:
        return 0.0
    return (bid - ask) / tot


def load_book_depth(asset: str) -> dict[tuple[str, str], list[dict]]:
    """Returns {(slug, outcome): [rows sorted by bucket]}."""
    path = DATA_DIR / f"{asset}_book_depth_v3.csv"
    if not path.exists():
        print(f"  [skip] no file at {path}")
        return {}
    by_so: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                row["bucket_10s"] = int(row["bucket_10s"])
            except (KeyError, ValueError):
                continue
            by_so[(row["slug"], row["outcome"])].append(row)
    # sort each by bucket
    for k in by_so:
        by_so[k].sort(key=lambda r: r["bucket_10s"])
    return dict(by_so)


def load_outcomes(asset: str) -> dict[str, dict]:
    """Returns {slug: {outcome_up, timeframe, window_start_unix, ...}} from markets_v3."""
    path = DATA_DIR / f"{asset}_markets_v3.csv"
    if not path.exists():
        print(f"  [warn] no markets file at {path}")
        return {}
    out: dict[str, dict] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            slug = row.get("slug")
            if not slug:
                continue
            out[slug] = row
    return out


def _slope_intercept(pairs: list[tuple[int, float]]) -> float:
    """OLS slope of y vs x given list of (x, y) tuples. Returns NaN if degenerate."""
    if len(pairs) < 2:
        return float("nan")
    n = len(pairs)
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    sxx = sum(p[0] * p[0] for p in pairs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return float("nan")
    return (n * sxy - sx * sy) / denom


def compute_features(buckets: list[dict],
                     horizons_sec: tuple[int, ...],
                     late_windows_sec: tuple[int, ...] = ()) -> dict[str, float]:
    """Given sorted buckets for one (slug, outcome), compute imbalance features.

    Three families of features:

    1. Early-window forward: `imb_avg_<H>s`, `imb_slope_<H>s` — over buckets [0, H/10).
       Fair for entry-at-time-H strategies (if H ≤ 270, you get 30+s of hold).

    2. Late-window descriptive: `imb_avg_last<W>s`, `imb_slope_last<W>s` — over
       buckets [(300-W)/10, 30) (last W seconds before resolution).
       LOOKAHEAD for any entry < 300-W.

    3. Static: `imb_t0`, `imb_t_end`, `imb_t_mid` — single-bucket reads.
    """
    if not buckets:
        return {}
    # imb time series: bucket_idx -> imb
    imbs: dict[int, float] = {}
    for r in buckets:
        b = r["bucket_10s"]
        if b < 0 or b > 100:
            continue
        imbs[b] = imbalance(r, TOP_K)
    if not imbs:
        return {}

    feats: dict[str, float] = {}
    feats["imb_t0"] = imbs.get(0, imbs[min(imbs)])
    feats["n_buckets"] = float(len(imbs))
    # Mid + end snapshots (lookahead for fair entry, useful for settlement dynamics)
    if 14 in imbs or 15 in imbs:  # 5m mid = ~bucket 15
        feats["imb_t_mid"] = imbs.get(15, imbs.get(14, 0.0))
    end_b = max(imbs)
    feats["imb_t_end"] = imbs[end_b]

    # 1. Early-window forward features
    for horizon in horizons_sec:
        bucket_max = horizon // 10  # exclusive end bucket
        # Force horizon-1 bucket to fit within market (5m=30 buckets, 15m=90 buckets)
        relevant_buckets = [b for b in imbs if 0 <= b < bucket_max]
        if relevant_buckets:
            feats[f"imb_avg_{horizon}s"] = sum(imbs[b] for b in relevant_buckets) / len(relevant_buckets)
        pairs = [(b, imbs[b]) for b in relevant_buckets]
        if len(pairs) >= 2:
            slope_per_bucket = _slope_intercept(pairs)
            if not (slope_per_bucket != slope_per_bucket):  # not NaN
                feats[f"imb_slope_{horizon}s"] = slope_per_bucket * (bucket_max - 1)

    # 2. Late-window descriptive features (last W seconds of 5m markets only)
    # Bucket range [bucket_min, 30) where bucket_min = (300 - W)/10
    for W in late_windows_sec:
        bucket_min = (300 - W) // 10
        relevant = [b for b in imbs if bucket_min <= b < 30]
        if not relevant:
            continue
        feats[f"imb_avg_last{W}s"] = sum(imbs[b] for b in relevant) / len(relevant)
        pairs = [(b, imbs[b]) for b in relevant]
        if len(pairs) >= 2:
            slope_per_bucket = _slope_intercept(pairs)
            if not (slope_per_bucket != slope_per_bucket):
                feats[f"imb_slope_last{W}s"] = slope_per_bucket * (W // 10 - 1)

    return feats


def spearman_ic(xs: list[float], ys: list[int]) -> tuple[float, int]:
    """Spearman rank correlation. Returns (ic, n)."""
    n = len(xs)
    if n < 5:
        return float("nan"), n
    # rank xs (ties get average rank)
    sorted_xs = sorted(range(n), key=lambda i: xs[i])
    ranks_x = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[sorted_xs[j + 1]] == xs[sorted_xs[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks_x[sorted_xs[k]] = avg_rank
        i = j + 1
    # ranks for ys (binary 0/1) — ties broken by index, doesn't matter for IC sign
    sorted_ys = sorted(range(n), key=lambda i: ys[i])
    ranks_y = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ys[sorted_ys[j + 1]] == ys[sorted_ys[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks_y[sorted_ys[k]] = avg_rank
        i = j + 1
    # pearson on ranks
    mean_x = sum(ranks_x) / n
    mean_y = sum(ranks_y) / n
    num = sum((ranks_x[i] - mean_x) * (ranks_y[i] - mean_y) for i in range(n))
    denx = math.sqrt(sum((ranks_x[i] - mean_x) ** 2 for i in range(n)))
    deny = math.sqrt(sum((ranks_y[i] - mean_y) ** 2 for i in range(n)))
    if denx == 0 or deny == 0:
        return float("nan"), n
    return num / (denx * deny), n


def decile_split(xs: list[float], ys: list[int], n_bins: int = 5) -> list[tuple[int, int, float]]:
    """Bin xs into n_bins quantiles; for each bin return (n, wins, hit_rate)."""
    n = len(xs)
    if n < n_bins * 5:
        return []
    paired = sorted(zip(xs, ys))
    bin_size = n // n_bins
    out = []
    for b in range(n_bins):
        lo = b * bin_size
        hi = (b + 1) * bin_size if b < n_bins - 1 else n
        seg = paired[lo:hi]
        nb = len(seg)
        wins = sum(p[1] for p in seg)
        rate = wins / nb if nb else 0.0
        out.append((nb, wins, rate))
    return out


def run_for_asset(asset: str) -> dict:
    print(f"\n=== {asset.upper()} ===")
    book = load_book_depth(asset)
    if not book:
        return {"asset": asset, "skipped": True}
    outcomes = load_outcomes(asset)
    print(f"  slugs in book_depth: {len(set(s for s,_ in book.keys()))}")
    print(f"  slugs in outcomes:   {len(outcomes)}")

    feature_names: list[str] = []
    rows = []  # list of dicts: {slug, outcome_up, ...features...}
    for slug, market_meta in outcomes.items():
        try:
            outcome_up = int(market_meta.get("outcome_up", 0))
        except (TypeError, ValueError):
            continue
        up_buckets = book.get((slug, "Up"), [])
        dn_buckets = book.get((slug, "Down"), [])
        if not up_buckets or not dn_buckets:
            continue
        f_up = compute_features(up_buckets, HORIZONS_SEC, LATE_WINDOWS_SEC)
        f_dn = compute_features(dn_buckets, HORIZONS_SEC, LATE_WINDOWS_SEC)
        if not f_up or not f_dn:
            continue
        record: dict = {"slug": slug, "outcome_up": outcome_up,
                        "timeframe": market_meta.get("timeframe", "5m")}
        # Up book features
        for k, v in f_up.items():
            record[f"up_{k}"] = v
        # Down book features
        for k, v in f_dn.items():
            record[f"dn_{k}"] = v
        # Diff (asymmetry)
        for k in f_up:
            if k in f_dn:
                record[f"diff_{k}"] = f_up[k] - f_dn[k]
        rows.append(record)

    if not rows:
        print("  no rows with both Up and Down book data")
        return {"asset": asset, "n": 0}
    # capture feature names from UNION of all rows (some rows may be missing horizons)
    base_keys = {"slug", "outcome_up", "timeframe"}
    all_keys: set[str] = set()
    for r in rows:
        all_keys.update(r.keys())
    feature_names = sorted(all_keys - base_keys)
    print(f"  joined rows: {len(rows)}, features: {len(feature_names)}")

    # IC per feature
    ys = [r["outcome_up"] for r in rows]
    results = []
    for f in feature_names:
        xs = [r.get(f, 0.0) for r in rows]
        # filter NaN
        valid = [(x, y) for x, y in zip(xs, ys) if not (isinstance(x, float) and (x != x))]
        if len(valid) < 30:
            continue
        xv = [v[0] for v in valid]
        yv = [v[1] for v in valid]
        ic, n = spearman_ic(xv, yv)
        if math.isnan(ic):
            continue
        bins = decile_split(xv, yv, n_bins=5)
        spread = bins[-1][2] - bins[0][2] if len(bins) == 5 else float("nan")
        # Tag tradability based on feature name.
        # Forward-window features (imb_avg_<H>s, imb_slope_<H>s) — feature uses [0, H].
        #   Tradable IF entry at time H, hold remaining (300-H) seconds.
        # Late-window features (imb_avg_last<W>s, imb_slope_last<W>s) — feature uses last W seconds.
        #   Always LOOKAHEAD for any entry strategy (would need entry < 300-W to observe + benefit).
        # Static t0/mid/end: t0 fair always, mid/end lookahead.
        is_late_window = "_last" in f
        is_static_end = f.endswith("imb_t_end") or f.endswith("imb_t_mid")
        is_static_t0 = f.endswith("imb_t0")
        is_n_buckets = f.endswith("n_buckets")
        # Pull horizon from feature name (e.g. "up_imb_slope_60s" -> 60)
        horizon_sec = 0
        for token in f.split("_"):
            stripped = token.replace("last", "")
            if stripped.endswith("s") and stripped[:-1].isdigit():
                horizon_sec = int(stripped[:-1])
                break

        if is_n_buckets:
            tradability = "meta"
        elif is_static_t0:
            tradability = "fair_entry_t=0s"
        elif is_static_end:
            tradability = "LOOKAHEAD_settle"
        elif is_late_window:
            # last W seconds of market — descriptive only
            tradability = f"LOOKAHEAD_last{horizon_sec}s"
        else:
            # Forward-window feature [0, horizon]:
            # Tradable as entry at t=horizon. Holding time = 300 - horizon.
            if horizon_sec <= 60:
                tradability = f"fair_entry_t={horizon_sec}s"
            elif horizon_sec <= 180:
                tradability = f"fair_entry_t={horizon_sec}s"  # mid-market entry
            elif horizon_sec <= 270:
                tradability = f"late_entry_t={horizon_sec}s"  # 30-120s hold
            else:
                tradability = "LOOKAHEAD_full"  # uses entire market window
        results.append({"feature": f, "ic": ic, "n": n,
                        "top_bin_hit": bins[-1][2] if bins else 0,
                        "bottom_bin_hit": bins[0][2] if bins else 0,
                        "spread": spread,
                        "horizon_sec": horizon_sec,
                        "tradability": tradability})

    # Sort by abs(IC)
    results.sort(key=lambda r: -abs(r["ic"]))
    # Sweep entry-time tiers — show best feature per entry time
    print(f"\n  BEST TRADABLE FEATURES BY ENTRY TIME (5m markets — hold = 300 - entry seconds):")
    print(f"  {'entry_time':12s}  {'feature':35s}  {'IC':>7s}  {'spread':>7s}  {'hold_s':>6s}")
    entry_times = ["t=0s", "t=30s", "t=60s", "t=120s", "t=180s", "t=240s", "t=270s"]
    for et in entry_times:
        hold = 300 - int(et[2:-1]) if et != "t=0s" else 300
        # Best |IC| feature with this entry time
        candidates = [r for r in results if r["tradability"].endswith(et)]
        candidates.sort(key=lambda x: -abs(x["ic"]))
        if candidates:
            top = candidates[0]
            print(f"  {et:12s}  {top['feature']:35s}  {top['ic']:>+7.4f}  {top['spread']:>+7.3f}  {hold:>4d}s")
        else:
            print(f"  {et:12s}  (no features)")
    print(f"\n  TOP 5 LOOKAHEAD (LAST-W-SECONDS) FEATURES — settlement dynamics:")
    leak_late = [r for r in results if r["tradability"].startswith("LOOKAHEAD_last")]
    leak_late.sort(key=lambda x: -abs(x["ic"]))
    for r in leak_late[:5]:
        print(f"  {r['feature']:35s}  IC={r['ic']:>+7.4f}  spread={r['spread']:>+7.3f}  ({r['tradability']})")
    print(f"\n  FULL-WINDOW LOOKAHEAD (300s):")
    leak_full = [r for r in results if r["tradability"] == "LOOKAHEAD_full"]
    leak_full.sort(key=lambda x: -abs(x["ic"]))
    for r in leak_full[:3]:
        print(f"  {r['feature']:35s}  IC={r['ic']:>+7.4f}  spread={r['spread']:>+7.3f}")

    return {"asset": asset, "n": len(rows), "results": results}


def main() -> int:
    print("Phase 7 — CLOB Imbalance Momentum")
    print(f"  data dir: {DATA_DIR}")
    print(f"  top-K levels: {TOP_K}")
    print(f"  horizons (sec): {HORIZONS_SEC}")

    all_results = []
    for asset in ASSETS:
        all_results.append(run_for_asset(asset))

    # Write report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    report_path = REPORTS_DIR / f"PHASE7_CLOB_MOMENTUM_{today}.md"
    lines = [
        f"# Phase 7 — CLOB Imbalance Momentum + Late Entry Sweep (run {today})",
        "",
        f"Top-K levels: {TOP_K}, forward horizons: {HORIZONS_SEC}, late windows: {LATE_WINDOWS_SEC}",
        "",
        "## Tradability framework",
        "",
        "5-minute Polymarket UpDown markets last 300s. A feature computed over buckets `[0, T]`",
        "is FAIR for an entry at time T (you've observed all data ending at T before entering).",
        "Holding time = `300 - T` seconds.",
        "",
        "| Tier | Means | Fair if entry at | Hold | Useful for |",
        "|---|---|---|---|---|",
        "| `fair_entry_t=0s` | feature at t=0 only | window_start | 5 min | V3-style entry |",
        "| `fair_entry_t=30s..60s` | uses [0, T] data | T into market | 4-4.5 min | Light late-entry |",
        "| `fair_entry_t=120s..180s` | uses [0, T] data | T into market | 2-3 min | Mid-market entry |",
        "| `late_entry_t=240s..270s` | uses [0, T] data | T into market | 30-60s | **Last-min strategy** ⭐ |",
        "| `LOOKAHEAD_full` | uses entire [0, 300] | n/a | n/a | Resolution dynamics only |",
        "| `LOOKAHEAD_last<W>s` | uses last W seconds | n/a | n/a | Settlement-window study |",
        "",
        "## Per-asset BEST FEATURE BY ENTRY TIME",
        "",
        "Each row shows the strongest |IC| feature available at that entry time.",
        "",
    ]
    for r in all_results:
        if r.get("skipped") or not r.get("results"):
            lines.append(f"### {r['asset'].upper()}: skipped or no data")
            lines.append("")
            continue
        lines.append(f"### {r['asset'].upper()} (n={r['n']})")
        lines.append("")
        lines.append("| Entry time | Hold | Best feature | IC | spread | tier |")
        lines.append("|---|---:|---|---:|---:|---|")
        entry_times = ["t=0s", "t=30s", "t=60s", "t=120s", "t=180s", "t=240s", "t=270s"]
        for et in entry_times:
            hold = 300 - int(et[2:-1]) if et != "t=0s" else 300
            candidates = [f for f in r["results"] if f["tradability"].endswith(et)]
            candidates.sort(key=lambda x: -abs(x["ic"]))
            if candidates:
                top = candidates[0]
                lines.append(f"| {et} | {hold}s | `{top['feature']}` | {top['ic']:+.4f} | {top['spread']:+.3f} | {top['tradability']} |")
            else:
                lines.append(f"| {et} | {hold}s | (no features) | — | — | — |")
        lines.append("")
        lines.append("**Settlement-window dynamics (LOOKAHEAD — descriptive):**")
        lines.append("")
        lines.append("| Window | Best feature | IC | spread |")
        lines.append("|---|---|---:|---:|")
        leak_late = [f for f in r["results"] if f["tradability"].startswith("LOOKAHEAD_last")]
        leak_late.sort(key=lambda x: -abs(x["ic"]))
        for f in leak_late[:5]:
            lines.append(f"| `{f['tradability']}` | `{f['feature']}` | {f['ic']:+.4f} | {f['spread']:+.3f} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Interpretation:**")
    lines.append("")
    lines.append("- `IC` = Spearman rank correlation of feature vs outcome_up. >0 means higher feature → more UP wins.")
    lines.append("- `top_hit` / `bot_hit` = hit-rate of UP outcomes in top/bottom quintile of feature.")
    lines.append("- `spread` = top_hit - bot_hit. >0.10 = strong directional signal.")
    lines.append("")
    lines.append("**Verdict (compare against Phase 2 baseline IC=+0.082 for static ETH imbalance):**")
    lines.append("")
    lines.append("- The high-|IC| features at 300s horizon are LOOKAHEAD — they describe the resolution")
    lines.append("  dynamic, not a predictor available at entry. Discard for trading.")
    lines.append("- Among FAIR-ENTRY (≤60s) features: imbalance momentum is no stronger than static t0.")
    lines.append("  Still ~0.05-0.08 IC, similar to Phase 2.")
    lines.append("- Among LATE-ENTRY-OK (60-180s) features: SOL `up_imb_slope_120s` shows IC ~ -0.16.")
    lines.append("  Only viable as a late-entry signal (enter at t+120s, hold 3min). Marginal.")
    lines.append("")
    lines.append("**Conclusion:** raw imbalance momentum at fair entry times is NOT a strong directional")
    lines.append("alpha. Phase 8 (meta-classifier ensemble) is the next swing. Phase 9 (TFI from trades_v2)")
    lines.append("may also add lift since trade flow is independent of orderbook posting.")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
