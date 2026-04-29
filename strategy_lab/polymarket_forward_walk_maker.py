"""
polymarket_forward_walk_maker.py — out-of-sample test for maker-entry hybrid (best variant).

Best variant from in-sample sweep: tick=0.01, wait=30s, fb=taker
  In-sample: +2.24pp ROI vs taker, 25% fill, 3/3 cross-asset, 4/5 days

Forward-walk per (asset, tf): chronological 80/20.
  - q10 quantile threshold fit on TRAIN only.
  - Apply maker-hybrid simulator on both train and holdout.
  - Compare to taker baseline same way.

Outputs:
  results/polymarket/forward_walk_maker.csv
  reports/POLYMARKET_FORWARD_WALK_MAKER.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import load_features, load_trajectories, load_klines_1m
from polymarket_maker_entry import simulate_maker_entry, simulate_taker_baseline

RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5

# Best variant
TICK_IMPROVE = 0.01
WAIT_BUCKETS = 3  # 30s
FALLBACK_TO_TAKER = True

OUT_CSV = HERE / "results" / "polymarket" / "forward_walk_maker.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_FORWARD_WALK_MAKER.md"


def split_chrono(df, train_frac=0.8):
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    cut = int(len(df) * train_frac)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def add_q10_with_train_threshold(df, train_df):
    out = df.copy()
    out["signal"] = -1
    for asset in out.asset.unique():
        for tf in out.timeframe.unique():
            train_sub = train_df[(train_df.asset == asset) & (train_df.timeframe == tf)]
            if len(train_sub) < 5:
                continue
            thr = train_sub.ret_5m.abs().dropna().quantile(0.90)
            sel = ((out.asset == asset) & (out.timeframe == tf)
                   & out.ret_5m.notna() & (out.ret_5m.abs() >= thr))
            out.loc[sel, "signal"] = (out.loc[sel, "ret_5m"] > 0).astype(int)
    return out[out.signal != -1].copy()


def evaluate(df_signal, traj, k1m, mode):
    """mode = 'taker' or 'maker'. Returns dict with stats."""
    pnls = []
    fills = 0
    cost_sum = 0.0
    for _, row in df_signal.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        if mode == "taker":
            r = simulate_taker_baseline(row, traj_g, k1m[row.asset], REV_BP)
        else:
            r = simulate_maker_entry(row, traj_g, k1m[row.asset], REV_BP,
                                      WAIT_BUCKETS, TICK_IMPROVE, FALLBACK_TO_TAKER)
        if r is None or not np.isfinite(r["pnl"]):
            continue
        pnls.append(r["pnl"])
        cost_sum += r["cost"]
        if mode == "maker" and r.get("filled_as_maker"):
            fills += 1
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"),
                "ci_lo": 0, "ci_hi": 0, "fill_rate": float("nan"),
                "mean_cost": 0, "total_pnl": 0}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "total_pnl": float(pnls.sum()),
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "fill_rate": float(fills / n) if mode == "maker" else float("nan"),
        "mean_cost": float(cost_sum / n),
    }


def main():
    print(f"Loading data... (rev_bp={REV_BP}, hedge-hold, tick={TICK_IMPROVE}, wait={WAIT_BUCKETS*10}s, fb=taker)")
    feats_by_asset = {a: load_features(a) for a in ASSETS}
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    k1m_by_asset = {a: load_klines_1m(a) for a in ASSETS}

    rows = []
    for tf in ["5m", "15m"]:
        for asset_filter in [None, "btc", "eth", "sol"]:
            if asset_filter:
                raw = feats_by_asset[asset_filter]
                raw = raw[raw.timeframe == tf].copy()
            else:
                raw = pd.concat([feats_by_asset[a][feats_by_asset[a].timeframe == tf]
                                 for a in ASSETS], ignore_index=True)
            if len(raw) < 50:
                continue

            train_raw, holdout_raw = split_chrono(raw, train_frac=0.8)
            train_signal = add_q10_with_train_threshold(train_raw, train_raw)
            holdout_signal = add_q10_with_train_threshold(holdout_raw, train_raw)

            tr_taker = evaluate(train_signal, traj_by_asset, k1m_by_asset, "taker")
            hd_taker = evaluate(holdout_signal, traj_by_asset, k1m_by_asset, "taker")
            tr_maker = evaluate(train_signal, traj_by_asset, k1m_by_asset, "maker")
            hd_maker = evaluate(holdout_signal, traj_by_asset, k1m_by_asset, "maker")

            row = {
                "tf": tf, "asset": asset_filter or "ALL",
                "tr_taker_n": tr_taker["n"], "tr_taker_hit": tr_taker["hit"], "tr_taker_roi": tr_taker["roi"],
                "hd_taker_n": hd_taker["n"], "hd_taker_hit": hd_taker["hit"], "hd_taker_roi": hd_taker["roi"],
                "hd_taker_ci_lo": hd_taker["ci_lo"], "hd_taker_ci_hi": hd_taker["ci_hi"],
                "tr_maker_n": tr_maker["n"], "tr_maker_hit": tr_maker["hit"], "tr_maker_roi": tr_maker["roi"],
                "tr_maker_fill": tr_maker["fill_rate"],
                "hd_maker_n": hd_maker["n"], "hd_maker_hit": hd_maker["hit"], "hd_maker_roi": hd_maker["roi"],
                "hd_maker_ci_lo": hd_maker["ci_lo"], "hd_maker_ci_hi": hd_maker["ci_hi"],
                "hd_maker_fill": hd_maker["fill_rate"],
                "tr_lift_pp": tr_maker["roi"] - tr_taker["roi"],
                "hd_lift_pp": hd_maker["roi"] - hd_taker["roi"],
            }
            rows.append(row)
            print(f"{tf:3s} {(asset_filter or 'ALL'):3s}: "
                  f"TRAIN taker n={tr_taker['n']:>3d} ROI={tr_taker['roi']:+.2f}% | "
                  f"maker ROI={tr_maker['roi']:+.2f}% (fill {tr_maker['fill_rate']*100:.0f}%, lift {row['tr_lift_pp']:+.2f}pp) | "
                  f"HOLDOUT taker n={hd_taker['n']:>3d} ROI={hd_taker['roi']:+.2f}% | "
                  f"maker ROI={hd_maker['roi']:+.2f}% (fill {hd_maker['fill_rate']*100:.0f}%, lift {row['hd_lift_pp']:+.2f}pp)")

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    md = ["# Forward-Walk: Maker-Entry Hybrid vs Taker Baseline\n",
          f"q10 chronological 80/20 split. Quantile threshold (90th percentile of |ret_5m|) fit on TRAIN only.",
          f"Both taker and maker simulators run on the same train and holdout sets.",
          f"Maker variant: limit at bid+0.01, wait 30s, fallback to taker if no fill.",
          f"Hedge-hold rev_bp=5 on exit (locked baseline).\n",
          "\n## TRAIN vs HOLDOUT — taker baseline (control)\n",
          "| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI |",
          "|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['tf']} | {r['asset']} | "
                  f"{r['tr_taker_n']} / {r['tr_taker_hit']*100:.1f}% / {r['tr_taker_roi']:+.2f}% | "
                  f"{r['hd_taker_n']} / {r['hd_taker_hit']*100:.1f}% / {r['hd_taker_roi']:+.2f}% / "
                  f"[{r['hd_taker_ci_lo']:+.2f}, {r['hd_taker_ci_hi']:+.2f}] |")

    md.append("\n## TRAIN vs HOLDOUT — maker hybrid\n")
    md.append("| TF | Asset | TRAIN n / hit / ROI / fill | HOLDOUT n / hit / ROI / fill / 95% CI |")
    md.append("|---|---|---|---|")
    for r in rows:
        md.append(f"| {r['tf']} | {r['asset']} | "
                  f"{r['tr_maker_n']} / {r['tr_maker_hit']*100:.1f}% / {r['tr_maker_roi']:+.2f}% / "
                  f"{r['tr_maker_fill']*100:.0f}% | "
                  f"{r['hd_maker_n']} / {r['hd_maker_hit']*100:.1f}% / {r['hd_maker_roi']:+.2f}% / "
                  f"{r['hd_maker_fill']*100:.0f}% / "
                  f"[{r['hd_maker_ci_lo']:+.2f}, {r['hd_maker_ci_hi']:+.2f}] |")

    md.append("\n## Lift table — maker minus taker\n")
    md.append("| TF | Asset | TRAIN lift | HOLDOUT lift | Verdict |")
    md.append("|---|---|---|---|---|")
    holdout_wins = 0
    holdout_total = 0
    for r in rows:
        if np.isnan(r["hd_lift_pp"]):
            verdict = "—"
        else:
            holdout_total += 1
            if r["hd_lift_pp"] > 0:
                holdout_wins += 1
                verdict = "✅ holdout lift positive"
            else:
                verdict = "❌ holdout lift negative"
        md.append(f"| {r['tf']} | {r['asset']} | "
                  f"{r['tr_lift_pp']:+.2f}pp | {r['hd_lift_pp']:+.2f}pp | {verdict} |")

    md.append(f"\n## Verdict\n")
    md.append(f"Holdout cells with positive maker lift: **{holdout_wins} / {holdout_total}**")
    if holdout_wins / max(holdout_total, 1) >= 0.7:
        md.append("\n✅ **Maker-entry edge GENERALIZES out-of-sample.** Deploy-ready.")
    elif holdout_wins / max(holdout_total, 1) >= 0.5:
        md.append("\n⚠️ **Borderline.** Maker lift mostly holds but mixed. Pilot with caution.")
    else:
        md.append("\n❌ **Edge does not generalize.** In-sample lift may be artifact of selection.")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")
    print(f"\nHoldout lift positive in {holdout_wins}/{holdout_total} cells")


if __name__ == "__main__":
    main()
