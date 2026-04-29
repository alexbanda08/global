"""
polymarket_volume_filter.py — E3: Volume regime filter (skip low-volume markets).

Hypothesis (from queue):
  Signal noise correlates with low Binance volume. Markets where the underlying spot
  is illiquid have less reliable price discovery, so our latency-arb signal is weaker.
  Skip low-volume markets to lift hit rate.

Volume features (computed at window_start):
  vol_5m_now    = Binance 5min volume at ws (sum of 1MIN volumes over [ws-300, ws])
  vol_24h_mean  = rolling 24h mean of 5min volume for that asset
  vol_z         = (vol_5m_now - vol_24h_mean) / vol_24h_std

Variants tested:
  baseline       : no filter (q10 + hedge-hold rev_bp=5)
  high_vol_only  : trade only when vol_z > 0 (above-average volume)
  high_vol_p25   : skip bottom 25% by vol_z (keep p25-p100)
  high_vol_p50   : skip bottom 50% by vol_z (keep p50-p100)
  exclude_p10    : skip bottom 10% (anomalously low)
  high_5m_thr    : trade only when vol_5m_now > threshold (e.g. p50)

Outputs:
  results/polymarket/volume_filter.csv
  reports/POLYMARKET_VOLUME_FILTER.md
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

OUT_CSV = HERE / "results" / "polymarket" / "volume_filter.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_VOLUME_FILTER.md"


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


def load_klines_with_volume(asset):
    """Re-load with volume column (load_klines_1m only returns close)."""
    k = pd.read_csv(HERE / "data" / "binance" / f"{asset}_klines_window.csv")
    k1m = k[k.period_id == "1MIN"].copy()
    k1m["ts_s"] = (k1m.time_period_start_us // 1_000_000).astype(int)
    # Volume column might be 'volume' or 'volume_traded'
    vol_col = None
    for c in ["volume", "volume_traded", "volume_quote", "volume_base"]:
        if c in k1m.columns:
            vol_col = c
            break
    if vol_col is None:
        raise ValueError(f"No volume column in {asset} klines. Cols: {k1m.columns.tolist()}")
    k1m["volume"] = k1m[vol_col].astype(float)
    return k1m.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close", "volume"]]


def compute_vol_features(feats, k1m_full_by_asset):
    out = feats.copy()
    out["vol_5m_now"] = float("nan")
    out["vol_24h_mean"] = float("nan")
    out["vol_24h_std"] = float("nan")
    for asset in ASSETS:
        k = k1m_full_by_asset[asset]
        # 5min rolling sum of volume (from minute bars)
        k = k.copy()
        k["vol5m"] = k["volume"].rolling(window=5, min_periods=5).sum()
        # 24h rolling mean and std of 5m volume
        k["vol24h_mean"] = k["vol5m"].rolling(window=1440, min_periods=60).mean()
        k["vol24h_std"] = k["vol5m"].rolling(window=1440, min_periods=60).std()
        sub_idx = (out.asset == asset)
        for idx in out[sub_idx].index:
            ws = int(out.at[idx, "window_start_unix"])
            j = k.ts_s.searchsorted(ws, side="right") - 1
            if j >= 0:
                out.at[idx, "vol_5m_now"] = float(k.vol5m.iloc[j]) if pd.notna(k.vol5m.iloc[j]) else float("nan")
                out.at[idx, "vol_24h_mean"] = float(k.vol24h_mean.iloc[j]) if pd.notna(k.vol24h_mean.iloc[j]) else float("nan")
                out.at[idx, "vol_24h_std"] = float(k.vol24h_std.iloc[j]) if pd.notna(k.vol24h_std.iloc[j]) else float("nan")
    out["vol_z"] = (out["vol_5m_now"] - out["vol_24h_mean"]) / out["vol_24h_std"]
    return out


def run_sim(df, traj, k1m, rev_bp=5):
    pnls = []
    rows = []
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
                         "ws": int(row.window_start_unix), "vol_z": row.get("vol_z", float("nan"))})
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
    # Need klines with volume
    k1m_full = {a: load_klines_with_volume(a) for a in ASSETS}
    # Also load close-only for simulator
    k1m = {a: load_klines_1m(a) for a in ASSETS}

    print("Computing volume features...")
    feats = compute_vol_features(feats, k1m_full)
    feats_q10 = add_q10_signal(feats)
    print(f"q10 markets: {len(feats_q10)}")

    vz = feats_q10["vol_z"].dropna()
    print(f"vol_z distribution: mean={vz.mean():.2f} median={vz.median():.2f} "
          f"p10={vz.quantile(0.10):.2f} p25={vz.quantile(0.25):.2f} "
          f"p50={vz.quantile(0.50):.2f} p75={vz.quantile(0.75):.2f} "
          f"p90={vz.quantile(0.90):.2f}")

    v5m = feats_q10["vol_5m_now"].dropna()
    print(f"vol_5m_now distribution: mean={v5m.mean():.0f} "
          f"p25={v5m.quantile(0.25):.0f} p50={v5m.quantile(0.50):.0f} "
          f"p75={v5m.quantile(0.75):.0f}")

    # Compute filter percentile thresholds
    vz_p10 = vz.quantile(0.10)
    vz_p25 = vz.quantile(0.25)
    vz_p50 = vz.quantile(0.50)

    variants = [
        ("baseline", lambda df: df.copy()),
        ("high_vol_only", lambda df: df[df.vol_z > 0].copy()),
        ("exclude_p10", lambda df: df[df.vol_z > vz_p10].copy()),
        ("exclude_p25", lambda df: df[df.vol_z > vz_p25].copy()),
        ("exclude_p50", lambda df: df[df.vol_z > vz_p50].copy()),
        ("only_high_vol_p75", lambda df: df[df.vol_z > vz.quantile(0.75)].copy()),
        ("only_extreme_vol_p90", lambda df: df[df.vol_z > vz.quantile(0.90)].copy()),
    ]

    rows_csv = []
    per_variant_rows = {}
    for label, filter_fn in variants:
        sub = filter_fn(feats_q10)
        s, rows_data = run_sim(sub, traj, k1m)
        rows_csv.append({"variant": label, "filter_n": len(sub), **s})
        per_variant_rows[label] = rows_data
        print(f"  {label:25s}: n={s['n']:>3d} hit={s['hit']*100:5.1f}% ROI={s['roi']:+6.2f}%")

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

    md = ["# Volume Regime Filter (E3)\n",
          f"Hypothesis: skip markets when Binance volume is anomalously low. "
          f"q10 universe (n={len(feats_q10)}). Hedge-hold rev_bp=5.\n",
          f"vol_z = (vol_5m_now - vol_24h_mean) / vol_24h_std. "
          f"Distribution: median {vz.median():.2f}, p10 {vz.quantile(0.10):.2f}, p90 {vz.quantile(0.90):.2f}.\n",
          "\n## Variant grid\n",
          "| Variant | n | Hit% | ROI | vs baseline | Trade rate |",
          "|---|---|---|---|---|---|"]
    for r in rows_csv:
        is_baseline = r["variant"] == "baseline"
        marker = " (baseline)" if is_baseline else (" ★" if r["variant"] == best["variant"] else "")
        lift = r.get("lift_vs_baseline", 0.0) if not is_baseline else 0
        rate = r["filter_n"] / baseline["n"] * 100
        md.append(f"| {r['variant']}{marker} | {r['n']} | {r['hit']*100:.1f}% | {r['roi']:+.2f}% | "
                  f"{lift:+.2f}pp | {rate:.0f}% |")

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
            sn, sb = len(sub), len(sub_b)
            sroi = np.mean([r["pnl"] for r in sub]) * 100
            broi = np.mean([r["pnl"] for r in sub_b]) * 100
            d = sroi - broi
            cross_lifts[(asset, tf)] = d
            md.append(f"| {asset} | {tf} | {sn} | {sroi:+.2f}% | {broi:+.2f}% | {d:+.2f}pp |")

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
        md.append(f"\n❌ No meaningful edge from volume filtering.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_csv).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
