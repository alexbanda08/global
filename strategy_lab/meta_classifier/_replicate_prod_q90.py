"""Replicate production's feed-backed q90 calibration for |ret_2m|.

PROBLEM (per HANDOFF_2026_05_22_MOMO_F7_MARKOV.md, next-step #5):
  My chainlink-only backtest (momo_variants_2abc.py) computes q90 over
  |ret_2m| samples drawn ONLY from chainlink-resolved slug timestamps.
  Production's `_fetch_abs_ret_2m_history` (poly_updown_loop.py) samples
  EVERY 1MIN binance kline over the rolling 14d window — many more
  samples, no resolution-status filter.

  Result: production's q90 threshold is materially lower than mine, and
  production fires ~10x more often. The momo_variants_2abc backtest fire
  count therefore understates the real strategy reach.

THIS SCRIPT:
  1. Loads canonical binance-spot-ws 1MIN closes for BTC/ETH/SOL.
  2. Computes |ret_2m| = |log(close@t / close@(t-120s))| for every 1m bar.
  3. Computes rolling 14d q90 of |ret_2m| at hourly anchors over the
     full 28d window — mirrors production's deque semantics with cheap
     pre-aggregation.
  4. Computes the chainlink-only q90 by restricting samples to slug-
     aligned timestamps (the universe momo_variants_2abc.py actually
     samples).
  5. For each asset reports: prod-q90 vs chainlink-q90 gap, and the
     projected fire-count delta if we swap the threshold.

OUTPUTS:
  data/v4/canonical/_results/prod_q90_calibration/
      hourly_thresholds.parquet      one row per (asset, hourly_anchor)
      per_asset_summary.json         single-number summary per asset
  strategy_lab/reports/PROD_Q90_REPLICATION_<run_date>.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_klines, load_resolutions  # noqa: E402

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results" / "prod_q90_calibration"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GATE_Q = 0.90
LOOKBACK_DAYS = 14


def load_per_asset_klines() -> dict:
    """Return dict[asset] = (ts_us int64 array, close float64 array,
                            abs_ret_2m float64 array)."""
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        df = load_klines(a, source="binance-spot-ws", period_id="1MIN")
        if df.empty:
            print(f"  [WARN] {a}: no klines")
            continue
        df = df.sort_values("time_period_start_us").reset_index(drop=True)
        ts_us = df.time_period_start_us.values.astype("int64")
        close = df.price_close.values.astype("float64")
        # |ret_2m| = |log(close[t] / close[t-2])| on minute index. Bars
        # spaced 60s but holes may exist - guard with index-based shift,
        # then mask if the 2-min gap isn't actually 120s.
        log_c = np.log(np.where(close > 0, close, np.nan))
        ret_2m = np.full_like(log_c, np.nan)
        ret_2m[2:] = log_c[2:] - log_c[:-2]
        # mask gaps where the actual elapsed seconds is not ~120
        if len(ts_us) > 2:
            dt = ts_us[2:] - ts_us[:-2]
            ret_2m[2:][dt != 120 * 1_000_000] = np.nan
        abs_ret_2m = np.abs(ret_2m)
        out[a] = (ts_us, close, abs_ret_2m)
        n_valid = int(np.isfinite(abs_ret_2m).sum())
        print(f"  {a}: 1MIN bars={len(ts_us):,}  valid_ret_2m={n_valid:,}  "
              f"span={pd.Timestamp(ts_us[0], unit='us', tz='UTC')} "
              f"-> {pd.Timestamp(ts_us[-1], unit='us', tz='UTC')}")
    return out


def hourly_anchors(ts_us: np.ndarray, lookback_days: int) -> np.ndarray:
    """Hourly UTC anchor timestamps from (start + lookback_days) to end."""
    t0 = ts_us[0]
    t1 = ts_us[-1]
    start = t0 + lookback_days * 24 * 3600 * 1_000_000
    if start >= t1:
        return np.array([], dtype="int64")
    # round to next hour
    h_us = 3600 * 1_000_000
    start = ((start + h_us - 1) // h_us) * h_us
    return np.arange(start, t1 + 1, h_us, dtype="int64")


def rolling_q90_at_anchors(
    ts_us: np.ndarray,
    abs_ret_2m: np.ndarray,
    anchors_us: np.ndarray,
    lookback_days: int,
    quantile: float = GATE_Q,
) -> np.ndarray:
    """For each anchor a, q-quantile of |ret_2m| over samples in [a-14d, a)."""
    win_us = lookback_days * 24 * 3600 * 1_000_000
    valid = np.isfinite(abs_ret_2m)
    vs_us = ts_us[valid]
    vv = abs_ret_2m[valid]
    qs = np.full(len(anchors_us), np.nan, dtype="float64")
    for i, a in enumerate(anchors_us):
        lo = int(np.searchsorted(vs_us, a - win_us, side="left"))
        hi = int(np.searchsorted(vs_us, a, side="right"))
        if hi - lo < 100:
            continue
        qs[i] = float(np.quantile(vv[lo:hi], quantile))
    return qs


def chainlink_q90_per_asset_tf(
    abs_ret_2m: np.ndarray,
    ts_us: np.ndarray,
    slug_us_array: np.ndarray,
    lookback_days: int,
    quantile: float = GATE_Q,
) -> tuple[float, int]:
    """Compute the "chainlink-only" q90: at each slug fire time, take 14d of
    |ret_2m| samples (slug-aligned ONLY) and quantile.

    Returns the MEDIAN q90 across all slug anchors AND the median window size.
    """
    win_us = lookback_days * 24 * 3600 * 1_000_000

    # For each slug timestamp, compute |ret_2m| AT that time (using nearest
    # 1m bar at-or-before). This emulates the per-slug sample momo_variants
    # gathers.
    valid_mask = np.isfinite(abs_ret_2m)
    valid_ts = ts_us[valid_mask]
    valid_val = abs_ret_2m[valid_mask]
    # for each slug us, find the |ret_2m| of the 1m bar ending at-or-before slug
    idx = np.searchsorted(valid_ts, slug_us_array, side="right") - 1
    keep = idx >= 0
    slug_us_array = slug_us_array[keep]
    idx = idx[keep]
    slug_abs = valid_val[idx]
    slug_anchor = valid_ts[idx]

    qs = []
    sizes = []
    for i in range(len(slug_anchor)):
        a = slug_anchor[i]
        lo = np.searchsorted(slug_anchor, a - win_us, side="left")
        hi = i  # samples before this one only (causal)
        if hi - lo < 50:
            continue
        sub = slug_abs[lo:hi]
        sub = sub[np.isfinite(sub)]
        if len(sub) < 50:
            continue
        qs.append(float(np.quantile(sub, quantile)))
        sizes.append(int(len(sub)))
    if not qs:
        return float("nan"), 0
    return float(np.median(qs)), int(np.median(sizes))


def fire_count_under_threshold(
    abs_ret_2m: np.ndarray, ts_us: np.ndarray,
    slug_us_array: np.ndarray, threshold: float,
) -> int:
    """How many slug-aligned moments exceed the threshold |ret_2m|?"""
    if not np.isfinite(threshold):
        return 0
    valid_mask = np.isfinite(abs_ret_2m)
    valid_ts = ts_us[valid_mask]
    valid_val = abs_ret_2m[valid_mask]
    idx = np.searchsorted(valid_ts, slug_us_array, side="right") - 1
    idx = idx[idx >= 0]
    return int((valid_val[idx] >= threshold).sum())


def main() -> int:
    print("[1] loading binance-spot-ws 1MIN klines per asset...")
    klines = load_per_asset_klines()

    print("\n[2] loading chainlink resolutions for slug timestamps...")
    res = load_resolutions()
    res = res.rename(columns={"ticker": "asset", "timeframe": "tf"})
    res = res[res.asset.isin(("BTC", "ETH", "SOL")) & res.tf.isin(("5m", "15m"))].copy()
    print(f"    {len(res):,} chainlink-resolved markets across BTC/ETH/SOL × 5m/15m")

    rows_hourly: list[pd.DataFrame] = []
    summary: dict[str, dict] = {}

    print("\n[3] computing rolling 14d q90 at hourly anchors (prod-style) "
          "+ chainlink-only q90 per asset...")
    for asset in ("BTC", "ETH", "SOL"):
        if asset not in klines:
            continue
        ts_us, _close, abs_ret_2m = klines[asset]
        anchors = hourly_anchors(ts_us, LOOKBACK_DAYS)
        prod_q = rolling_q90_at_anchors(
            ts_us, abs_ret_2m, anchors, LOOKBACK_DAYS, GATE_Q,
        )
        n_samples_per_anchor = LOOKBACK_DAYS * 24 * 60  # ~20160 if no gaps

        df_h = pd.DataFrame(dict(
            asset=asset,
            anchor_us=anchors,
            anchor_ts=pd.to_datetime(anchors, unit="us", utc=True),
            prod_q90=prod_q,
        ))
        rows_hourly.append(df_h)

        # Per-tf chainlink-only q90
        per_tf: dict[str, dict] = {}
        for tf in ("5m", "15m"):
            sub = res[(res.asset == asset) & (res.tf == tf)].copy()
            slug_us = sub.slot_start_us.values.astype("int64")
            slug_us.sort()
            cl_q90, cl_n = chainlink_q90_per_asset_tf(
                abs_ret_2m, ts_us, slug_us, LOOKBACK_DAYS, GATE_Q,
            )
            # fire-count comparison at median prod_q90 vs chainlink_q90
            prod_q90_median = float(np.nanmedian(prod_q))
            n_fires_prod = fire_count_under_threshold(
                abs_ret_2m, ts_us, slug_us, prod_q90_median,
            )
            n_fires_cl = fire_count_under_threshold(
                abs_ret_2m, ts_us, slug_us, cl_q90,
            )
            ratio = (n_fires_prod / n_fires_cl) if n_fires_cl else float("nan")
            per_tf[tf] = dict(
                slug_count=int(len(slug_us)),
                prod_q90_median=prod_q90_median,
                chainlink_q90_median=cl_q90,
                chainlink_q90_window_size=cl_n,
                n_fires_above_prod_q90=n_fires_prod,
                n_fires_above_chainlink_q90=n_fires_cl,
                fire_ratio_prod_over_chainlink=ratio,
            )
            print(f"  {asset} {tf:>3}: prod q90={prod_q90_median:.6f}  "
                  f"chainlink q90={cl_q90:.6f}  "
                  f"fires (prod thr / chainlink thr)= "
                  f"{n_fires_prod:>5} / {n_fires_cl:>5}  ratio={ratio:.2f}x")

        summary[asset] = dict(
            n_kline_bars=int(len(ts_us)),
            n_valid_ret_2m=int(np.isfinite(abs_ret_2m).sum()),
            prod_q90_median_all=float(np.nanmedian(prod_q)),
            prod_q90_p10_all=float(np.nanpercentile(prod_q, 10)) if np.any(np.isfinite(prod_q)) else float("nan"),
            prod_q90_p90_all=float(np.nanpercentile(prod_q, 90)) if np.any(np.isfinite(prod_q)) else float("nan"),
            n_hourly_anchors=int(len(anchors)),
            n_samples_per_anchor_target=int(n_samples_per_anchor),
            per_tf=per_tf,
        )

    hourly = pd.concat(rows_hourly, ignore_index=True)
    hourly.to_parquet(OUT_DIR / "hourly_thresholds.parquet", index=False)
    (OUT_DIR / "per_asset_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(f"\nSaved: {OUT_DIR / 'hourly_thresholds.parquet'}")
    print(f"Saved: {OUT_DIR / 'per_asset_summary.json'}")

    write_markdown_report(summary, hourly)
    return 0


def write_markdown_report(summary: dict, hourly: pd.DataFrame) -> None:
    run_date = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    out = ROOT / "strategy_lab" / "reports" / f"PROD_Q90_REPLICATION_{run_date}.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md: list[str] = []
    md.append(f"# Production q90 replication - chainlink vs feed-backed ({now})")
    md.append("")
    md.append("Replicates production's `_fetch_abs_ret_2m_history` calibration "
              "(feed-backed deque, every 1MIN bar, rolling 14d) and compares "
              "to the chainlink-only q90 used in `momo_variants_2abc.py`.")
    md.append("")
    md.append("## Method")
    md.append("")
    md.append("- For each asset, compute |ret_2m| = |log(close@t / close@(t-120s))| "
              "on every binance-spot-ws 1MIN bar.")
    md.append("- Prod-q90: hourly rolling 14d q90 over ALL bars - emulates the "
              "production deque sampled at each fire decision.")
    md.append("- Chainlink-q90: rolling 14d q90 sampled ONLY at slug-aligned "
              "timestamps per (asset, tf) - emulates `momo_variants_2abc.py`.")
    md.append("- Fire-count proxy: count slug timestamps where |ret_2m| >= threshold.")
    md.append("")
    md.append("## Per-asset summary (q90 magnitudes)")
    md.append("")
    md.append("| Asset | n_bars | n_valid | prod_q90 median | prod_q90 p10 | prod_q90 p90 |")
    md.append("|---|--:|--:|--:|--:|--:|")
    for a, s in summary.items():
        md.append(f"| {a} | {s['n_kline_bars']:,} | {s['n_valid_ret_2m']:,} | "
                  f"{s['prod_q90_median_all']:.6f} | {s['prod_q90_p10_all']:.6f} | "
                  f"{s['prod_q90_p90_all']:.6f} |")
    md.append("")
    md.append("## Threshold and fire-count delta per (asset, tf)")
    md.append("")
    md.append("| Asset | tf | n_slugs | prod q90 | chainlink q90 | "
              "fires above prod | fires above chainlink | ratio |")
    md.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for a, s in summary.items():
        for tf, d in s["per_tf"].items():
            md.append(
                f"| {a} | {tf} | {d['slug_count']:,} | {d['prod_q90_median']:.6f} | "
                f"{d['chainlink_q90_median']:.6f} | "
                f"{d['n_fires_above_prod_q90']:,} | "
                f"{d['n_fires_above_chainlink_q90']:,} | "
                f"{d['fire_ratio_prod_over_chainlink']:.2f}x |"
            )
    md.append("")
    md.append("## Interpretation")
    md.append("")
    md.append("- If `prod q90 < chainlink q90`, the production calibration is "
              "LOOSER than ours and would fire MORE often - this is the "
              "expected direction per the handoff.")
    md.append("- The `fire_ratio_prod_over_chainlink` column tells you exactly "
              "how many more fires you'd see if you swapped the threshold.")
    md.append("- The actual production fire rate also depends on the universe "
              "(production includes binance-resolved markets we drop). The ratio "
              "here measures the ISOLATED effect of the threshold calibration.")
    md.append("")
    md.append("## Next step")
    md.append("")
    md.append("To close the gap in `momo_variants_2abc.py`:")
    md.append("")
    md.append("1. For each fire candidate timestamp `t`, look up "
              "`hourly_thresholds.parquet` at the most recent hourly anchor "
              "<= `t`.")
    md.append("2. Use that `prod_q90` as the fire gate instead of the per-slug "
              "rolling q90.")
    md.append("3. Re-run the variants backtest - expect ~Nx more fires per "
              "the ratios above.")
    md.append("")
    md.append(f"_data: `data/v4/canonical/_results/prod_q90_calibration/`_  ")
    md.append(f"_generated by `strategy_lab/meta_classifier/_replicate_prod_q90.py`_")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"Report: {out}")


if __name__ == "__main__":
    sys.exit(main())
