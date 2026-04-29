"""
polymarket_microstructure_filter.py — E4: skip thin-book / wide-spread markets.

Hypothesis (from queue):
  Markets with wide spreads or shallow books have:
    - Worse fills (already shown in E1 capacity ladder)
    - Likely worse signal-to-fee ratio because the move needs to overcome more friction
  Skipping these may lift hit rate by 2-4pp.

Microstructure features (from book_depth_v3 at bucket_0):
  spread_pct       = (ask_0 - bid_0) / mid                  (in %)
  top_size_usd     = ask_size_0 * ask_price_0 (held side)   (USD)
  n_levels_ask     = number of non-null ask price levels (out of 10)
  n_levels_bid     = number of non-null bid price levels
  depth_5lvl_usd   = sum of (price * size) over top 5 ask levels (held side)

Variants tested:
  baseline                : no filter (q10 + hedge-hold rev_bp=5)
  spread_lt_4pct          : skip if spread > 4% of mid
  spread_lt_2pct          : skip if spread > 2% of mid (tighter)
  top_size_gt_25usd       : skip if top-of-book USD < $25
  top_size_gt_100usd      : skip if top-of-book USD < $100
  n_levels_ge_5           : require at least 5 non-null ask levels
  combined_quality        : spread_lt_4 AND top_size_gt_25
  combined_strict         : spread_lt_2 AND top_size_gt_100 AND n_levels_ge_5

Outputs:
  results/polymarket/microstructure_filter.csv
  reports/POLYMARKET_MICROSTRUCTURE_FILTER.md
"""
from __future__ import annotations
from pathlib import Path
import sys
import math
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import load_features, load_trajectories, load_klines_1m, simulate_market

RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
LEVELS = 10
REV_BP = 5

OUT_CSV = HERE / "results" / "polymarket" / "microstructure_filter.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_MICROSTRUCTURE_FILTER.md"


def add_q10_signal(df):
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            r_abs = df.loc[m, "ret_5m"].abs()
            thr = r_abs.quantile(0.90)
            sel = m & (df.ret_5m.abs() >= thr) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def load_book_depth(asset):
    """Index by (slug, bucket, outcome) → (asks, sizes, bids, bid_sizes) at first bucket."""
    df = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_book_depth_v3.csv")
    cols_ask_p = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_ask_s = [f"ask_size_{i}"  for i in range(LEVELS)]
    cols_bid_p = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bid_s = [f"bid_size_{i}"  for i in range(LEVELS)]
    asks_p = df[cols_ask_p].to_numpy(dtype=float)
    asks_s = df[cols_ask_s].to_numpy(dtype=float)
    bids_p = df[cols_bid_p].to_numpy(dtype=float)
    bids_s = df[cols_bid_s].to_numpy(dtype=float)
    out = {}
    slugs = df.slug.to_numpy()
    buckets = df.bucket_10s.to_numpy(dtype=int)
    outcomes = df.outcome.to_numpy()
    for i in range(len(df)):
        if int(buckets[i]) != 0:
            continue
        s = slugs[i]; oc = outcomes[i]
        out.setdefault(s, {})[oc] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


def compute_micro_features(row, book_by_asset):
    """Compute microstructure features for the held side at bucket 0."""
    sig = int(row.signal)
    held = "Up" if sig == 1 else "Down"
    book = book_by_asset[row.asset].get(row.slug, {}).get(held)
    if book is None:
        return {"spread_pct": float("nan"), "top_size_usd": float("nan"),
                "n_levels_ask": 0, "n_levels_bid": 0, "depth_5lvl_usd": 0.0}
    ask_p, ask_s, bid_p, bid_s = book
    a0 = ask_p[0] if np.isfinite(ask_p[0]) else float("nan")
    b0 = bid_p[0] if np.isfinite(bid_p[0]) else float("nan")
    if np.isfinite(a0) and np.isfinite(b0):
        mid = (a0 + b0) / 2
        spread_pct = (a0 - b0) / mid * 100 if mid > 0 else float("nan")
    else:
        spread_pct = float("nan")
    top_size_usd = float(a0 * ask_s[0]) if np.isfinite(a0) and np.isfinite(ask_s[0]) else float("nan")
    n_ask = sum(1 for i in range(LEVELS) if np.isfinite(ask_p[i]) and np.isfinite(ask_s[i]) and ask_s[i] > 0)
    n_bid = sum(1 for i in range(LEVELS) if np.isfinite(bid_p[i]) and np.isfinite(bid_s[i]) and bid_s[i] > 0)
    depth_5 = sum(ask_p[i] * ask_s[i] for i in range(min(5, LEVELS))
                  if np.isfinite(ask_p[i]) and np.isfinite(ask_s[i]))
    return {"spread_pct": spread_pct, "top_size_usd": top_size_usd,
            "n_levels_ask": n_ask, "n_levels_bid": n_bid, "depth_5lvl_usd": float(depth_5)}


def run_sim(df, traj, k1m, rev_bp=REV_BP):
    pnls, rows = [], []
    for _, row in df.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        p = simulate_market(row, traj_g, k1m[row.asset],
                            target=None, stop=None, rev_bp=rev_bp,
                            merge_aware=False, hedge_hold=True)
        if p is not None and np.isfinite(p):
            pnls.append(p)
            rows.append({"pnl": p, "asset": row.asset, "tf": row.timeframe,
                         "ws": int(row.window_start_unix)})
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"), "ci_lo": 0, "ci_hi": 0}, []
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
    }, rows


def main():
    print("Loading...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    book_by_asset = {a: load_book_depth(a) for a in ASSETS}

    feats_q10 = add_q10_signal(feats)
    print(f"q10 markets: {len(feats_q10)}")

    print("Computing microstructure features...")
    micro_rows = []
    for _, row in feats_q10.iterrows():
        f = compute_micro_features(row, book_by_asset)
        micro_rows.append(f)
    micro_df = pd.DataFrame(micro_rows, index=feats_q10.index)
    df = pd.concat([feats_q10, micro_df], axis=1)
    df = df.dropna(subset=["spread_pct", "top_size_usd"]).copy()
    print(f"Markets with valid micro features: {len(df)}")

    print(f"\nspread_pct: median {df.spread_pct.median():.2f}% "
          f"p25 {df.spread_pct.quantile(0.25):.2f}% p75 {df.spread_pct.quantile(0.75):.2f}%")
    print(f"top_size_usd: median ${df.top_size_usd.median():.0f} "
          f"p25 ${df.top_size_usd.quantile(0.25):.0f} p75 ${df.top_size_usd.quantile(0.75):.0f}")
    print(f"n_levels_ask: median {df.n_levels_ask.median():.0f} "
          f"min {df.n_levels_ask.min()} max {df.n_levels_ask.max()}")

    variants = [
        ("baseline", lambda d: d.copy()),
        ("spread_lt_4pct", lambda d: d[d.spread_pct < 4.0].copy()),
        ("spread_lt_2pct", lambda d: d[d.spread_pct < 2.0].copy()),
        ("top_size_gt_25usd", lambda d: d[d.top_size_usd > 25].copy()),
        ("top_size_gt_100usd", lambda d: d[d.top_size_usd > 100].copy()),
        ("n_levels_ge_5", lambda d: d[d.n_levels_ask >= 5].copy()),
        ("n_levels_ge_8", lambda d: d[d.n_levels_ask >= 8].copy()),
        ("combined_quality",
         lambda d: d[(d.spread_pct < 4) & (d.top_size_usd > 25)].copy()),
        ("combined_strict",
         lambda d: d[(d.spread_pct < 2) & (d.top_size_usd > 100) & (d.n_levels_ask >= 5)].copy()),
    ]

    rows_csv = []
    per_variant_rows = {}
    for label, filter_fn in variants:
        sub = filter_fn(df)
        s, sim_rows = run_sim(sub, traj, k1m)
        rows_csv.append({"variant": label, "filter_n": len(sub), **s})
        per_variant_rows[label] = sim_rows
        print(f"  {label:25s}: filter_n={len(sub):>3d} sim_n={s['n']:>3d} "
              f"hit={s['hit']*100 if not np.isnan(s['hit']) else 0:5.1f}% "
              f"ROI={s['roi']:+6.2f}%")

    baseline = next(r for r in rows_csv if r["variant"] == "baseline")
    others = [r for r in rows_csv if r["variant"] != "baseline"]
    for r in others:
        r["lift_vs_baseline"] = r["roi"] - baseline["roi"]
    others.sort(key=lambda x: x["roi"], reverse=True)
    best = others[0]
    print(f"\nBaseline: ROI={baseline['roi']:+.2f}%")
    print(f"Best: {best['variant']}: ROI={best['roi']:+.2f}% (lift {best['lift_vs_baseline']:+.2f}pp)")

    # Cross-asset for best
    best_rows = per_variant_rows[best["variant"]]
    base_rows = per_variant_rows["baseline"]

    md = ["# Microstructure Filter (E4)\n",
          f"Hypothesis: skip thin-book / wide-spread markets to lift signal-to-fee ratio.",
          f"q10 universe (n={len(df)} after dropping markets without book at bucket 0). "
          f"Hedge-hold rev_bp={REV_BP}.\n",
          f"\n## Microstructure feature distribution at bucket 0\n",
          f"- spread_pct: median {df.spread_pct.median():.2f}% (p25 {df.spread_pct.quantile(0.25):.2f}%, "
          f"p75 {df.spread_pct.quantile(0.75):.2f}%)",
          f"- top_size_usd: median ${df.top_size_usd.median():.0f} "
          f"(p25 ${df.top_size_usd.quantile(0.25):.0f}, p75 ${df.top_size_usd.quantile(0.75):.0f})",
          f"- n_levels_ask: median {int(df.n_levels_ask.median())} (min {int(df.n_levels_ask.min())}, "
          f"max {int(df.n_levels_ask.max())})",
          "\n## Variant grid\n",
          "| Variant | n | Hit% | ROI | vs baseline | Volume kept |",
          "|---|---|---|---|---|---|"]
    for r in rows_csv:
        is_baseline = r["variant"] == "baseline"
        marker = " (baseline)" if is_baseline else (" ★" if r["variant"] == best["variant"] else "")
        lift = r.get("lift_vs_baseline", 0.0) if not is_baseline else 0
        rate = r["filter_n"] / baseline["n"] * 100 if baseline["n"] else 0
        md.append(f"| {r['variant']}{marker} | {r['n']} | "
                  f"{r['hit']*100 if not np.isnan(r['hit']) else 0:.1f}% | "
                  f"{r['roi']:+.2f}% | {lift:+.2f}pp | {rate:.0f}% |")

    # Cross-asset for best
    md.append(f"\n## Cross-asset breakdown — best `{best['variant']}` vs baseline\n")
    md.append("| Asset | TF | best n | best ROI | baseline ROI | Δ |")
    md.append("|---|---|---|---|---|---|")
    cross_lifts = {}
    for asset in ["ALL", "btc", "eth", "sol"]:
        for tf in ["ALL", "5m", "15m"]:
            sub = [r for r in best_rows
                   if (asset == "ALL" or r["asset"] == asset)
                   and (tf == "ALL" or r["tf"] == tf)]
            sub_b = [r for r in base_rows
                     if (asset == "ALL" or r["asset"] == asset)
                     and (tf == "ALL" or r["tf"] == tf)]
            if not sub or not sub_b:
                continue
            sroi = np.mean([r["pnl"] for r in sub]) * 100
            broi = np.mean([r["pnl"] for r in sub_b]) * 100
            d = sroi - broi
            cross_lifts[(asset, tf)] = d
            md.append(f"| {asset} | {tf} | {len(sub)} | {sroi:+.2f}% | {broi:+.2f}% | {d:+.2f}pp |")

    # Day-by-day
    df_best = pd.DataFrame(best_rows); df_base = pd.DataFrame(base_rows)
    df_best["dt"] = pd.to_datetime(df_best.ws, unit="s", utc=True); df_best["date"] = df_best.dt.dt.date
    df_base["dt"] = pd.to_datetime(df_base.ws, unit="s", utc=True); df_base["date"] = df_base.dt.dt.date
    md.append(f"\n## Day-by-day — best `{best['variant']}` vs baseline\n")
    md.append("| Date | best n | best ROI | baseline ROI | Δ |")
    md.append("|---|---|---|---|---|")
    days_lift = 0
    for d in sorted(df_best.date.unique()):
        sub = df_best[df_best.date == d]; sub_b = df_base[df_base.date == d]
        roi = sub.pnl.mean() * 100 if len(sub) else 0
        roi_b = sub_b.pnl.mean() * 100 if len(sub_b) else 0
        delta = roi - roi_b
        if delta > 0:
            days_lift += 1
        md.append(f"| {d} | {len(sub)} | {roi:+.2f}% | {roi_b:+.2f}% | {delta:+.2f}pp |")

    # Verdict
    n_criteria = 0
    if best["lift_vs_baseline"] > 0:
        n_criteria += 1
    cross_count = sum(1 for asset in ["btc", "eth", "sol"] if cross_lifts.get((asset, "ALL"), 0) > 0)
    if cross_count >= 2:
        n_criteria += 1
    if days_lift >= 4:
        n_criteria += 1
    md.append("\n## Verdict\n")
    md.append(f"**Criteria: {n_criteria}/3**")
    md.append(f"  - In-sample lift > 0: {'✅' if best['lift_vs_baseline'] > 0 else '❌'} "
              f"({best['lift_vs_baseline']:+.2f}pp)")
    md.append(f"  - Cross-asset (≥2/3): {'✅' if cross_count >= 2 else '❌'} ({cross_count}/3)")
    md.append(f"  - Day stability (≥4/5): {'✅' if days_lift >= 4 else '❌'} "
              f"({days_lift}/{df_best.date.nunique()})")
    if n_criteria >= 2:
        md.append(f"\n⚠️ Worth forward-walk validation.")
    else:
        md.append(f"\n❌ No meaningful edge from microstructure filtering.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_csv).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
