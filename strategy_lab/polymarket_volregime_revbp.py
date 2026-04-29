"""
polymarket_volregime_revbp.py — E7: vol-regime adaptive rev_bp threshold.

Hypothesis (from queue):
  rev_bp=5 is optimal on average but may over-hedge in high-vol regimes (5bp triggers
  on every normal move) and under-hedge in low-vol regimes (5bp rarely fires when
  it should). Adaptive rev_bp scaled by current vol regime should beat the fixed
  baseline.

Vol features (computed at window_start):
  vol_5m_now    = |BTC ret_5m| at ws (the signal magnitude itself)
  vol_24h_mean  = rolling 24h mean of |ret_5m| for that asset
  vol_ratio     = vol_5m_now / vol_24h_mean

Variants tested:
  V0_static5      : rev_bp=5 (baseline)
  V1_static3      : rev_bp=3 (control: tighter)
  V2_static8      : rev_bp=8 (control: wider)
  V3_atr_linear   : rev_bp = clip(5 * vol_ratio, 3, 20)
  V4_atr_sqrt     : rev_bp = clip(5 * sqrt(vol_ratio), 3, 20) — gentler scaling
  V5_quintile     : rev_bp = {3, 4, 5, 7, 10} for vol quintiles 1..5
  V6_inverse      : rev_bp = clip(5 / vol_ratio, 3, 20) — opposite (tighter when vol rises)
                     [included as sanity check / null hypothesis]

Outputs:
  results/polymarket/volregime_revbp.csv
  reports/POLYMARKET_VOLREGIME_REVBP.md
"""
from __future__ import annotations
from pathlib import Path
import sys
import math
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import load_features, load_trajectories, load_klines_1m

RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
FEE_RATE = 0.02

OUT_CSV = HERE / "results" / "polymarket" / "volregime_revbp.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_VOLREGIME_REVBP.md"


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


def asof_close(k1m, ts):
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def compute_ret_5m(k1m, ts):
    """log(close[ts] / close[ts-300])"""
    p_now = asof_close(k1m, ts)
    p_prior = asof_close(k1m, ts - 300)
    if not (np.isfinite(p_now) and np.isfinite(p_prior)) or p_prior <= 0:
        return float("nan")
    return math.log(p_now / p_prior)


def compute_vol_features(feats: pd.DataFrame, k1m_by_asset: dict) -> pd.DataFrame:
    """Add vol_5m_now and vol_24h_mean and vol_ratio per row."""
    out = feats.copy()
    out["vol_5m_now"] = out["ret_5m"].abs()
    # rolling 24h mean of |ret_5m| per asset (use the markets' own ret_5m as a proxy
    # since we don't have continuous returns easily available — instead compute from klines).
    # For each asset, compute |ret_5m| at every minute over the data window, then rolling mean.
    out["vol_24h_mean"] = float("nan")
    for asset in ASSETS:
        k = k1m_by_asset[asset].copy()
        k["abs_ret5m"] = float("nan")
        # ret_5m at each minute
        for i in range(5, len(k)):
            p_now = float(k.price_close.iloc[i])
            p_prior = float(k.price_close.iloc[i-5])
            if p_prior > 0 and p_now > 0:
                k.loc[k.index[i], "abs_ret5m"] = abs(math.log(p_now / p_prior))
        # rolling 24h = 1440 minutes
        k["vol24h"] = k["abs_ret5m"].rolling(window=1440, min_periods=60).mean()
        # For each market in this asset, look up vol24h at window_start
        sub_idx = (out.asset == asset)
        for idx in out[sub_idx].index:
            ws = int(out.at[idx, "window_start_unix"])
            j = k.ts_s.searchsorted(ws, side="right") - 1
            if j >= 0:
                v = k.vol24h.iloc[j]
                if pd.notna(v):
                    out.at[idx, "vol_24h_mean"] = float(v)
    out["vol_ratio"] = out["vol_5m_now"] / out["vol_24h_mean"]
    return out


def map_rev_bp(vol_ratio, mode):
    """Compute dynamic rev_bp based on vol_ratio."""
    if pd.isna(vol_ratio) or vol_ratio <= 0:
        return 5  # fallback to baseline
    if mode == "static5":
        return 5
    if mode == "static3":
        return 3
    if mode == "static8":
        return 8
    if mode == "atr_linear":
        return max(3, min(20, 5.0 * vol_ratio))
    if mode == "atr_sqrt":
        return max(3, min(20, 5.0 * math.sqrt(vol_ratio)))
    if mode == "inverse":
        return max(3, min(20, 5.0 / vol_ratio))
    raise ValueError(f"Unknown mode: {mode}")


def map_rev_bp_quintile(vol_ratio, quintile_thresholds):
    """5 quintiles: rev_bp = {3,4,5,7,10} for q1..q5 of vol_ratio."""
    if pd.isna(vol_ratio):
        return 5
    levels = [3, 4, 5, 7, 10]
    for i, t in enumerate(quintile_thresholds):
        if vol_ratio <= t:
            return levels[i]
    return levels[-1]


def simulate_with_dyn_revbp(row, traj_g, k1m, rev_bp_dyn):
    """Hedge-hold with per-row rev_bp."""
    sig = int(row.signal)
    entry = float(row.entry_yes_ask) if sig == 1 else float(row.entry_no_ask)
    if not (np.isfinite(entry) and 0 < entry < 1):
        return None
    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge_p = None
    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue
        if not np.isfinite(btc_at_ws):
            continue
        ts_in = ws + bucket * 10
        btc_now = asof_close(k1m, ts_in)
        if not np.isfinite(btc_now):
            continue
        bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
        reverted = (sig == 1 and bp <= -rev_bp_dyn) or (sig == 0 and bp >= rev_bp_dyn)
        if reverted:
            col = "dn_ask_min" if sig == 1 else "up_ask_min"
            oa = b.get(col, float("nan"))
            if pd.notna(oa) and 0 < oa < 1:
                hedge_p = float(oa)
                break
    sig_won = (sig == int(row.outcome_up))
    if hedge_p is None:
        if sig_won:
            return 1.0 - (1.0 - entry) * FEE_RATE - entry, entry, "natural_win", rev_bp_dyn
        return -entry, entry, "natural_lose", rev_bp_dyn
    if sig_won:
        payout = 1.0 - (1.0 - entry) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_p) * FEE_RATE
    return payout - entry - hedge_p, entry + hedge_p, "hedged", rev_bp_dyn


def stat_block(rows):
    pnls = np.array([r["pnl"] for r in rows])
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"),
                "ci_lo": 0, "ci_hi": 0, "hedge_rate": float("nan"),
                "mean_revbp": float("nan")}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    hedged = sum(1 for r in rows if r["kind"] == "hedged")
    return {
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hedge_rate": float(hedged / n),
        "mean_revbp": float(np.mean([r["revbp"] for r in rows])),
    }


def main():
    print("Loading...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}

    print("Computing vol features (24h rolling mean)...")
    feats = compute_vol_features(feats, k1m)
    feats_q10 = add_q10_signal(feats)
    print(f"q10 markets: {len(feats_q10)}")
    print(f"  vol_ratio distribution:")
    vr = feats_q10["vol_ratio"].dropna()
    print(f"    mean={vr.mean():.2f} median={vr.median():.2f}")
    print(f"    p10={vr.quantile(0.10):.2f} p25={vr.quantile(0.25):.2f} "
          f"p50={vr.quantile(0.50):.2f} p75={vr.quantile(0.75):.2f} "
          f"p90={vr.quantile(0.90):.2f}")

    # Quintile thresholds
    q_thresholds = [vr.quantile(q) for q in [0.20, 0.40, 0.60, 0.80]] + [float("inf")]

    variants = [
        ("V0_static5",     "static5",     False),
        ("V1_static3",     "static3",     False),
        ("V2_static8",     "static8",     False),
        ("V3_atr_linear",  "atr_linear",  False),
        ("V4_atr_sqrt",    "atr_sqrt",    False),
        ("V5_quintile",    "quintile",    True),
        ("V6_inverse",     "inverse",     False),
    ]

    rows_csv = []
    per_variant_rows = {}

    for label, mode, use_quintile in variants:
        sim_rows = []
        for _, row in feats_q10.iterrows():
            traj_g = traj[row.asset].get(row.slug)
            if traj_g is None or traj_g.empty:
                continue
            vr_val = row["vol_ratio"]
            if use_quintile:
                rev_bp_dyn = map_rev_bp_quintile(vr_val, q_thresholds)
            else:
                rev_bp_dyn = map_rev_bp(vr_val, mode)
            r = simulate_with_dyn_revbp(row, traj_g, k1m[row.asset], rev_bp_dyn)
            if r is not None:
                pnl, cost, kind, rb = r
                if np.isfinite(pnl):
                    sim_rows.append({"pnl": pnl, "cost": cost, "kind": kind,
                                     "revbp": rb, "asset": row.asset, "tf": row.timeframe,
                                     "ws": int(row.window_start_unix), "vol_ratio": vr_val})
        per_variant_rows[label] = sim_rows
        s = stat_block(sim_rows)
        rows_csv.append({"variant": label, "mode": mode, **s})
        print(f"  {label:20s}: n={s['n']:>3d} hit={s['hit']*100:5.1f}% ROI={s['roi']:+6.2f}% "
              f"hedge={s['hedge_rate']*100:.0f}% mean_revbp={s['mean_revbp']:.2f}")

    baseline = next(r for r in rows_csv if r["variant"] == "V0_static5")
    others = [r for r in rows_csv if r["variant"] != "V0_static5"]
    for r in others:
        r["lift_vs_baseline"] = r["roi"] - baseline["roi"]
    others.sort(key=lambda x: x["roi"], reverse=True)
    best = others[0]
    print(f"\nBaseline (V0 static5): ROI={baseline['roi']:+.2f}%")
    print(f"Best: {best['variant']}: ROI={best['roi']:+.2f}% (lift {best['lift_vs_baseline']:+.2f}pp)")

    md = ["# Vol-Regime Adaptive rev_bp (E7) — does adaptive hedge threshold beat fixed?\n",
          "Hypothesis: scale rev_bp by current vol regime to avoid over-/under-hedging.\n",
          f"q10 universe (n={len(feats_q10)}). Vol ratio = |ret_5m_now| / |ret_5m|_24h_mean.",
          f"\nVol ratio distribution: mean={vr.mean():.2f} median={vr.median():.2f} "
          f"p10={vr.quantile(0.10):.2f} p90={vr.quantile(0.90):.2f}\n",
          "## Variant grid\n",
          "| Variant | Description | n | Hit% | ROI | vs V0 baseline | Hedge rate | Mean rev_bp |",
          "|---|---|---|---|---|---|---|---|"]
    descriptions = {
        "V0_static5": "rev_bp = 5 (locked baseline)",
        "V1_static3": "rev_bp = 3 (always tighter)",
        "V2_static8": "rev_bp = 8 (always wider)",
        "V3_atr_linear": "rev_bp = clip(5*vol_ratio, 3, 20)",
        "V4_atr_sqrt": "rev_bp = clip(5*sqrt(vol_ratio), 3, 20)",
        "V5_quintile": "5 quintiles → {3,4,5,7,10}",
        "V6_inverse": "rev_bp = clip(5/vol_ratio, 3, 20) — sanity null",
    }
    for r in rows_csv:
        is_baseline = r["variant"] == "V0_static5"
        marker = " (baseline)" if is_baseline else (" ★" if r["variant"] == best["variant"] else "")
        lift = r.get("lift_vs_baseline", 0.0) if not is_baseline else 0
        md.append(f"| {r['variant']}{marker} | {descriptions.get(r['variant'], r['mode'])} | "
                  f"{r['n']} | {r['hit']*100:.1f}% | {r['roi']:+.2f}% | {lift:+.2f}pp | "
                  f"{r['hedge_rate']*100:.0f}% | {r['mean_revbp']:.2f} |")

    # Cross-asset for best
    best_rows = per_variant_rows[best["variant"]]
    base_rows = per_variant_rows["V0_static5"]
    md.append(f"\n## Cross-asset breakdown — best `{best['variant']}` vs V0 baseline\n")
    md.append("| Asset | TF | best n | best ROI | V0 ROI | Δ |")
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
            s = stat_block(sub); t = stat_block(sub_b)
            d = s["roi"] - t["roi"]
            cross_lifts[(asset, tf)] = d
            md.append(f"| {asset} | {tf} | {s['n']} | {s['roi']:+.2f}% | {t['roi']:+.2f}% | {d:+.2f}pp |")

    # Day-by-day
    df_best = pd.DataFrame(best_rows); df_base = pd.DataFrame(base_rows)
    df_best["dt"] = pd.to_datetime(df_best.ws, unit="s", utc=True); df_best["date"] = df_best.dt.dt.date
    df_base["dt"] = pd.to_datetime(df_base.ws, unit="s", utc=True); df_base["date"] = df_base.dt.dt.date
    md.append(f"\n## Day-by-day — best `{best['variant']}` vs V0 baseline\n")
    md.append("| Date | best n | best ROI | V0 ROI | Δ |")
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
        md.append(f"\n⚠️ Worth forward-walk validation. Adaptive rev_bp may help.")
    else:
        md.append(f"\n❌ Vol-regime adaptive rev_bp does NOT beat fixed rev_bp=5. "
                  f"The locked baseline already captures the optimal trade-off.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_csv).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
