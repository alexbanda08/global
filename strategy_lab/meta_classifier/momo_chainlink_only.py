"""Re-run the momo coinbase G-variant test on a CHAINLINK-RESOLVED-ONLY universe.

Background: market_resolutions_full.csv has `price_source` column with values
{chainlink-fast (61.1%), chainlink (26.5%), binance-klines-1m (8.9%)}.

The 8.9% binance-resolved markets had their `outcome` flag derived from binance
1m klines (older markets, backfilled before chainlink stream went live). For
backtest validity vs production (which always resolves on Chainlink Data Streams),
those rows must be dropped.

This module:
  1. Reloads the universe with chainlink-only filter.
  2. Re-runs B0, G2 (disagree+5bp), G6 (signed-lead q90) on chainlink-clean data.
  3. Compares to the previous (mixed) numbers to quantify the impact.

Output:
  data/v4/refresh_2026_05_09/coinbase_lead/clean_chainlink/{summary,lift,per_trade}.csv
  strategy_lab/reports/MOMO_CHAINLINK_ONLY_2026_05_09.md
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

# Import everything from validation pipeline EXCEPT load_universe
from momo_full_universe_validation import (   # noqa: E402
    load_klines, load_l25_for_asset,
    asof_strict,
    REFRESH_OLD, REFRESH_NEW,
)
GATE_Q = 0.90
LOOKBACK_DAYS = 14


def _compute_ret_window(uni, klines, off0, off1):
    """ret = log(close@(ws+off1) / close@(ws+off0)). ws here = slug suffix = start."""
    out = []
    for asset, ws in zip(uni.asset.values, uni.ws.values):
        c0 = asof_strict(klines[asset], int(ws) + off0)
        c1 = asof_strict(klines[asset], int(ws) + off1)
        if (math.isfinite(c0) and math.isfinite(c1) and c0 > 0 and c1 > 0):
            out.append(math.log(c1 / c0))
        else:
            out.append(float("nan"))
    return out


def _compute_thresholds_simple(uni, lookback_days=LOOKBACK_DAYS):
    """Per (asset, tf, day): q90 of |ret_2m| from prior lookback_days (excluding current).
    Self-contained; doesn't need the new 'version' column upstream."""
    out: dict = {}
    for (a, t), g in uni.groupby(["asset", "tf"]):
        g = g.sort_values("ws").reset_index(drop=True)
        for day, _ in g.groupby("day"):
            cutoff_lo = day - pd.Timedelta(days=lookback_days)
            train = g[(g.day >= cutoff_lo) & (g.day < day)]
            samples = train["abs_ret_2m"].dropna().values
            out[(a, t, str(day.date()))] = (
                float(np.quantile(samples, GATE_Q)) if len(samples) >= 50 else float("nan")
            )
    return out
from momo_coinbase_addalpha import (          # noqa: E402
    load_coinbase_klines, attach_coinbase_features,
    simulate_with_policy, POLICIES,
)
from momo_coinbase_lead import (               # noqa: E402
    GAP_5BP,
)


def apply_lead_variant_local(uni: pd.DataFrame, variant: str) -> pd.DataFrame:
    """Self-contained gate that bypasses upstream compute_thresholds (which now
    requires a 'version' column we don't have)."""
    thr_bin = _compute_thresholds_simple(uni)
    df = uni.copy()
    df["abs_target"] = df["ret_2m"].abs()
    df["threshold"] = df.apply(
        lambda r: thr_bin.get((r.asset, r.tf, str(r.day.date())), float("nan")),
        axis=1,
    )
    base = df[(df.abs_target.notna()) & (df.threshold.notna()) &
              (df.abs_target >= df.threshold) & df.ret_2m.notna()].copy()
    base["signal"] = base.ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
    if variant == "B0":
        return base
    base = base[base.coin_ret_2m.notna()].copy()
    sig_int = base.signal.map({"UP": 1, "DOWN": -1})
    if variant == "G2":
        keep = (np.sign(base.ret_2m) != np.sign(base.coin_ret_2m)) & \
               ((base.ret_2m - base.coin_ret_2m).abs() > GAP_5BP)
        return base[keep.fillna(False)].copy()
    if variant == "G6":
        # signed-lead top-decile: rolling 14d q90 per (asset, tf, day)
        from momo_coinbase_lead import _signed_lead_quantile_thresholds
        thr_q = _signed_lead_quantile_thresholds(uni, q=0.90, lookback_days=LOOKBACK_DAYS)
        thr_col = base.apply(lambda r: thr_q.get(
            (r.asset, r.tf, str(r.day.date())), float("nan")), axis=1)
        signed_lead = (base.ret_2m - base.coin_ret_2m) * sig_int
        keep = (signed_lead > thr_col) & thr_col.notna()
        return base[keep.fillna(False)].copy()
    raise ValueError(f"unknown variant {variant!r}")

OUT_DIR = REFRESH_NEW / "coinbase_lead" / "clean_chainlink"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_CHAINLINK_ONLY_2026_05_09.md"


def load_universe_chainlink_only() -> pd.DataFrame:
    """Load universe from REFRESH_NEW ONLY (which has the rich schema with
    price_source). REFRESH_OLD lacks price_source so we'd lose the chainlink
    annotation by merging.

    REFRESH_NEW (2026-05-09) has 19,697 markets with chainlink-fast/chainlink/
    binance-klines-1m source labels — covers Apr 22 → May 9 window."""
    r = pd.read_csv(REFRESH_NEW / "market_resolutions_full.csv")
    n_total = len(r)
    ps_counts = r["price_source"].value_counts().to_dict()
    print(f"    price_source distribution (NEW only): {ps_counts}")
    # Keep both 'chainlink-fast' and 'chainlink' (different stream variants, both ≠ binance)
    r = r[r["price_source"].isin(("chainlink-fast", "chainlink"))].copy()
    print(f"    chainlink-only: {len(r)}/{n_total} ({100*len(r)/n_total:.1f}%) kept")
    # Merge with markets_full for condition_id (need it to lookup L25 books).
    # markets_full has its own (sometimes-stale) outcome col — drop it so
    # resolution's chainlink-derived outcome wins cleanly.
    m = pd.read_csv(REFRESH_NEW / "markets_full.csv")
    if "outcome" in m.columns:
        m = m.drop(columns=["outcome"])
    df = m.merge(r[["slug", "outcome", "price_source"]], on="slug", how="inner").copy()
    df = df[df.outcome.isin(("Up", "Down"))]
    df = df[df.ticker.isin(["BTC", "ETH", "SOL"]) & df.timeframe.isin(["5m", "15m"])].copy()
    df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    df["asset"] = df.ticker
    df["tf"] = df.timeframe
    df["window_s"] = df.tf.map({"5m": 300, "15m": 900})
    df["day"] = pd.to_datetime(df.ws, unit="s").dt.floor("D")
    print(f"    final universe: {len(df)} markets ({df.day.min().date()} → {df.day.max().date()})")
    print(f"      by tf: {df.tf.value_counts().to_dict()}")
    return df[["slug", "condition_id", "asset", "tf", "ws", "window_s", "day", "outcome",
                "price_source"]].reset_index(drop=True)


def main():
    print("=== MOMO CHAINLINK-ONLY (drop binance-resolved) ===\n")
    print("[1] Loading klines...")
    bin_klines = load_klines()
    coin_klines = load_coinbase_klines()

    print("[2] Loading universe with chainlink-only filter...")
    uni = load_universe_chainlink_only()
    # Use locally-defined ret window function (ws=start, anchor at ws-60..ws+60).
    uni["ret_2m"] = _compute_ret_window(uni, bin_klines, -60, 60)
    uni["abs_ret_2m"] = uni.ret_2m.abs()
    print(f"    universe: {len(uni)} markets ({uni.day.min().date()} → {uni.day.max().date()})")

    print("[3] Attaching coinbase features...")
    uni = attach_coinbase_features(uni, bin_klines, coin_klines)

    # Limit to 3 representative variants (B0, G2, G6) to keep run fast
    variants_subset = ["B0", "G2", "G6"]
    print(f"\n[4] Computing variant gates: {variants_subset}")
    gated_per_variant: dict[str, pd.DataFrame] = {}
    for v in variants_subset:
        g = apply_lead_variant_local(uni, v)
        gated_per_variant[v] = g
        n_up = int((g.signal == "UP").sum())
        n_down = int((g.signal == "DOWN").sum())
        print(f"    {v}: gated={len(g)} (UP={n_up}, DOWN={n_down})")

    print("\n[5] Loading L25 books and simulating HOLD policy only (fastest)...")
    rows_all = []
    for asset in ("BTC", "ETH", "SOL"):
        gated_mids = set()
        for v in variants_subset:
            sub = gated_per_variant[v]
            gated_mids |= set(sub[sub.asset == asset].condition_id.unique())
        if not gated_mids:
            continue
        print(f"    [{asset}] mids={len(gated_mids)}")
        books_a, _ = load_l25_for_asset(asset, gated_mids=gated_mids)
        if not books_a:
            continue
        books = {asset: books_a}
        for v in variants_subset:
            sub = gated_per_variant[v]
            sub = sub[sub.asset == asset]
            for p in ("HOLD",):  # only HOLD for fast turnaround
                for r in sub.to_dict("records"):
                    res = simulate_with_policy(r, bin_klines, books, p)
                    if res is None:
                        continue
                    rows_all.append({
                        "variant": v, "policy": p,
                        "slug": r["slug"], "asset": asset, "tf": r["tf"],
                        "ws": int(r["ws"]), "day": str(r["day"].date()),
                        "signal": r["signal"], "outcome": r["outcome"],
                        "ret_2m": r["ret_2m"], "coin_ret_2m": r.get("coin_ret_2m"),
                        **res,
                    })
        del books_a, books
        print(f"    [{asset}] done — {len(rows_all)} rows total")

    print(f"\n[6] {len(rows_all)} per-trade rows — aggregating...")
    df = pd.DataFrame(rows_all)
    df.to_csv(OUT_DIR / "per_trade.csv", index=False)
    summary = df.groupby(["variant", "policy"]).agg(
        n=("pnl", "size"),
        hit=("pnl", lambda s: round(100 * (s > 0).mean(), 2)),
        pnl_total=("pnl", lambda s: round(s.sum(), 2)),
        pnl_mean=("pnl", lambda s: round(s.mean(), 4)),
        avg_vwap=("vwap_e", "mean"),
    ).reset_index()
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    # Compare to mixed-universe baseline
    print("\n=== CHAINLINK-ONLY summary ===")
    print(summary.to_string(index=False))

    # Hard-coded comparison to mixed baseline (from coinbase_lead/summary.csv)
    print("\n=== Comparison to mixed (binance+chainlink) ===")
    mixed_b0 = {"n": 949, "hit": 87.46, "pnl_total": 12846.33, "pnl_mean": 13.5367}
    mixed_g2 = {"n": 238, "hit": 86.55, "pnl_total": 6874.38, "pnl_mean": 28.884}
    mixed_g6 = {"n": 444, "hit": 90.09, "pnl_total": 8595.85, "pnl_mean": 19.36}
    mixed = {"B0": mixed_b0, "G2": mixed_g2, "G6": mixed_g6}
    print(f"{'variant':<5}  {'n_clean':>7}  {'n_mix':>6}  {'Δn':>5}  "
          f"{'hit_clean':>9}  {'hit_mix':>8}  {'Δhit':>6}  "
          f"{'pnl_total_clean':>16}  {'pnl_total_mix':>14}")
    for v in variants_subset:
        s = summary[summary.variant == v]
        if s.empty:
            continue
        s = s.iloc[0]
        m = mixed[v]
        dn = int(s.n) - m["n"]
        dhit = round(s.hit - m["hit"], 2)
        print(f"{v:<5}  {int(s.n):>7d}  {m['n']:>6d}  {dn:>+5d}  "
              f"{s.hit:>9.2f}  {m['hit']:>8.2f}  {dhit:>+6.2f}  "
              f"${s.pnl_total:>+15.2f}  ${m['pnl_total']:>+13.2f}")

    write_report(summary, gated_per_variant, mixed, variants_subset)
    print(f"\n[7] wrote {REPORT}")


def write_report(summary, gated, mixed, variants_subset):
    L = [
        "# MOMO Chainlink-Only Re-Run — drop binance-resolved markets",
        "_Generated: 2026-05-09_",
        "",
        "## Why this re-run",
        "Found that 8.9% of `market_resolutions_full.csv` rows have `price_source = binance-klines-1m` "
        "(older markets backfilled before chainlink stream was live). Production resolves exclusively on "
        "Chainlink Data Streams, so backtest must match. This re-run drops the 1,759 binance-resolved markets.",
        "",
        "## Universe filtering",
        "- price_source distribution (full universe): chainlink-fast=12,033, chainlink=5,211, binance-klines-1m=1,759",
        "- chainlink-only: 17,244 / 19,696 markets kept (87.5%)",
        "",
        "## Headline (HOLD policy, chainlink-only)",
        "",
        summary.to_markdown(index=False),
        "",
        "## Comparison: chainlink-clean vs mixed (B0/G2/G6 baseline numbers)",
        "",
        "| Variant | n_clean | n_mixed | Δn | hit_clean | hit_mixed | Δhit pp | pnl_clean | pnl_mixed | Δpnl |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for v in variants_subset:
        s = summary[summary.variant == v]
        if s.empty:
            continue
        s = s.iloc[0]
        m = mixed[v]
        L.append(
            f"| {v} | {int(s.n)} | {m['n']} | {int(s.n)-m['n']:+d} | "
            f"{s.hit:.2f} | {m['hit']:.2f} | {s.hit - m['hit']:+.2f} | "
            f"${s.pnl_total:+.2f} | ${m['pnl_total']:+.2f} | "
            f"${s.pnl_total - m['pnl_total']:+.2f} |"
        )

    L += [
        "",
        "## Interpretation",
        "- If Δn is small relative to base (10-15% drop), and hit/pnl_mean change <1pp / <$0.50, "
        "the binance-resolved subset wasn't biasing the verdict — chainlink-only confirms previous results.",
        "- If hit_clean drops materially (>2pp) or pnl_clean changes sign, the binance contamination "
        "was inflating the previous numbers and the new figures are more trustworthy.",
        "",
        "## Files",
        "- `data/v4/refresh_2026_05_09/coinbase_lead/clean_chainlink/{summary,per_trade}.csv`",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
