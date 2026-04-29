"""
polymarket_cross_asset_validate.py — validate the S2 (own_AND_btc_lag0_agree) signal:
  - Per-asset breakdown (ETH vs SOL)
  - Day-by-day stability
  - Forward-walk holdout 80/20

Best in-sample: n=247, hit 84.2%, ROI +26.61% (lift +3.67pp vs S0 baseline +22.94%).
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
TARGET_ASSETS = ["eth", "sol"]
REV_BP = 5

OUT_MD = HERE / "reports" / "POLYMARKET_CROSS_ASSET_VALIDATE.md"
OUT_CSV = HERE / "results" / "polymarket" / "cross_asset_validate.csv"


def compute_btc_ret(btc_k1m, ws, lag_s=0):
    end_ts = ws - lag_s
    start_ts = end_ts - 300
    end_idx = btc_k1m.ts_s.searchsorted(end_ts, side="right") - 1
    start_idx = btc_k1m.ts_s.searchsorted(start_ts, side="right") - 1
    if end_idx < 0 or start_idx < 0:
        return float("nan")
    p_end = float(btc_k1m.price_close.iloc[end_idx])
    p_start = float(btc_k1m.price_close.iloc[start_idx])
    if p_start <= 0:
        return float("nan")
    return math.log(p_end / p_start)


def add_q10_in_cell(df, col, train_df=None):
    """Add q10 signal based on `col` quantile fitted on train_df (or df itself)."""
    src = train_df if train_df is not None else df
    out = df.copy()
    sig_name = f"sig_{col}_q10"
    out[sig_name] = -1
    for asset in out.asset.unique():
        for tf in out.timeframe.unique():
            train_sub = src[(src.asset == asset) & (src.timeframe == tf)]
            r_abs = train_sub[col].abs().dropna()
            if r_abs.empty:
                continue
            thr = r_abs.quantile(0.90)
            sel = ((out.asset == asset) & (out.timeframe == tf)
                   & out[col].notna() & (out[col].abs() >= thr))
            out.loc[sel, sig_name] = (out.loc[sel, col] > 0).astype(int)
    return out, sig_name


def sim(df, signal_col, traj, k1m, rev_bp=REV_BP):
    sub = df[df[signal_col] != -1].copy()
    sub = sub.rename(columns={signal_col: "signal"})
    pnls = []
    rows = []
    for _, row in sub.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        p = simulate_market(row, traj_g, k1m[row.asset],
                            target=None, stop=None, rev_bp=rev_bp,
                            merge_aware=False, hedge_hold=True)
        if p is not None and np.isfinite(p):
            pnls.append(p)
            rows.append({"asset": row.asset, "tf": row.timeframe, "slug": row.slug,
                         "ws": int(row.window_start_unix), "pnl": p, "sig": int(row.signal)})
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"),
                "ci_lo": 0, "ci_hi": 0}, []
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
    }, rows


def build_s2_signal(df, ret_col_own="ret_5m", ret_col_btc="btc_ret_lag0", train_df=None):
    """S2: trade only when own_q10 AND btc_q10 agree direction."""
    df, own_sig = add_q10_in_cell(df, ret_col_own, train_df)
    df, btc_sig = add_q10_in_cell(df, ret_col_btc, train_df)
    df["sig_s2"] = -1
    agree_up = (df[own_sig] == 1) & (df[btc_sig] == 1)
    agree_dn = (df[own_sig] == 0) & (df[btc_sig] == 0)
    df.loc[agree_up | agree_dn, "sig_s2"] = df.loc[agree_up | agree_dn, own_sig]
    return df


def main():
    print("Loading...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    btc_k = k1m["btc"]
    feats["btc_ret_lag0"] = feats["window_start_unix"].apply(lambda ws: compute_btc_ret(btc_k, int(ws), 0))

    target_df = feats[feats.asset.isin(TARGET_ASSETS)].copy().reset_index(drop=True)
    print(f"ETH+SOL universe: {len(target_df)}")

    # ===== In-sample: per-asset breakdown =====
    md = ["# Cross-Asset Leader — Validation Report\n",
          "Best in-sample variant from E6: **S2 = own_q10 AND btc_lag0_q10 agree direction**\n"]
    md.append("\n## Per-asset × timeframe breakdown (in-sample)\n")
    md.append("| Asset | TF | S2 n | S2 hit | S2 ROI | own_q10 n | own_q10 ROI | lift |")
    md.append("|---|---|---|---|---|---|---|---|")

    rows_csv = []

    for asset in ["ALL", "eth", "sol"]:
        for tf in ["ALL", "5m", "15m"]:
            sub = target_df if asset == "ALL" else target_df[target_df.asset == asset]
            if tf != "ALL":
                sub = sub[sub.timeframe == tf]
            if len(sub) == 0:
                continue
            sub_with = build_s2_signal(sub.copy())
            sub_own, own_sig_col = add_q10_in_cell(sub.copy(), "ret_5m")
            s2_stats, _ = sim(sub_with, "sig_s2", traj, k1m)
            own_stats, _ = sim(sub_own, own_sig_col, traj, k1m)
            lift = s2_stats["roi"] - own_stats["roi"] if not np.isnan(s2_stats["roi"]) else float("nan")
            md.append(f"| {asset} | {tf} | {s2_stats['n']} | "
                      f"{s2_stats['hit']*100 if not np.isnan(s2_stats['hit']) else 0:.1f}% | "
                      f"{s2_stats['roi']:+.2f}% | "
                      f"{own_stats['n']} | {own_stats['roi']:+.2f}% | "
                      f"{lift:+.2f}pp |")
            rows_csv.append({"phase": "in_sample", "asset": asset, "tf": tf,
                             "s2_n": s2_stats['n'], "s2_hit": s2_stats['hit'], "s2_roi": s2_stats['roi'],
                             "own_n": own_stats['n'], "own_roi": own_stats['roi'], "lift_pp": lift})

    # ===== Day-by-day =====
    md.append("\n## Day-by-day (in-sample, S2 vs own_q10)\n")
    md.append("| Date | S2 n | S2 ROI | own n | own ROI | lift |")
    md.append("|---|---|---|---|---|---|")
    sub_with = build_s2_signal(target_df.copy())
    sub_own, own_sig_col = add_q10_in_cell(target_df.copy(), "ret_5m")
    _, s2_rows = sim(sub_with, "sig_s2", traj, k1m)
    _, own_rows = sim(sub_own, own_sig_col, traj, k1m)
    df_s2 = pd.DataFrame(s2_rows); df_own = pd.DataFrame(own_rows)
    df_s2["dt"] = pd.to_datetime(df_s2.ws, unit="s", utc=True); df_s2["date"] = df_s2.dt.dt.date
    df_own["dt"] = pd.to_datetime(df_own.ws, unit="s", utc=True); df_own["date"] = df_own.dt.dt.date
    days_lift = 0
    for d in sorted(df_s2.date.unique()):
        s2sub = df_s2[df_s2.date == d]
        ownsub = df_own[df_own.date == d]
        s2roi = s2sub.pnl.mean() * 100 if len(s2sub) else 0
        ownroi = ownsub.pnl.mean() * 100 if len(ownsub) else 0
        delta = s2roi - ownroi
        if delta > 0:
            days_lift += 1
        md.append(f"| {d} | {len(s2sub)} | {s2roi:+.2f}% | {len(ownsub)} | {ownroi:+.2f}% | {delta:+.2f}pp |")

    # ===== Forward-walk per (asset, tf) =====
    md.append("\n## Forward-walk holdout (80/20 chronological per asset×tf)\n")
    md.append("Quantile thresholds for both own_q10 and btc_lag0_q10 fit on TRAIN only.\n")
    md.append("| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Δhit | Verdict |")
    md.append("|---|---|---|---|---|---|")
    holdout_lifts = []
    for tf in ["5m", "15m"]:
        for asset in TARGET_ASSETS:
            sub = target_df[(target_df.asset == asset) & (target_df.timeframe == tf)].copy()
            sub = sub.sort_values("window_start_unix").reset_index(drop=True)
            cut = int(len(sub) * 0.8)
            train, holdout = sub.iloc[:cut].copy(), sub.iloc[cut:].copy()

            train_signal = build_s2_signal(train, train_df=train)
            holdout_signal = build_s2_signal(holdout, train_df=train)
            tr_stats, _ = sim(train_signal, "sig_s2", traj, k1m)
            hd_stats, _ = sim(holdout_signal, "sig_s2", traj, k1m)

            # Also compute own_q10 holdout for comparison
            train_own = add_q10_in_cell(train.copy(), "ret_5m", train_df=train)[0]
            holdout_own = add_q10_in_cell(holdout.copy(), "ret_5m", train_df=train)[0]
            tr_own_stats, _ = sim(train_own, "sig_ret_5m_q10", traj, k1m)
            hd_own_stats, _ = sim(holdout_own, "sig_ret_5m_q10", traj, k1m)

            d_hit = (tr_stats["hit"] - hd_stats["hit"]) * 100 if not np.isnan(hd_stats["hit"]) else float("nan")
            verdict = "—"
            if hd_stats["n"] > 0 and not np.isnan(hd_stats["hit"]):
                if abs(d_hit) <= 5 and hd_stats["ci_lo"] > 0:
                    verdict = "✅ generalizes"
                elif hd_stats["ci_lo"] > 0:
                    verdict = "⚠️ hit drift"
                else:
                    verdict = "❌"
            md.append(f"| {tf} | {asset} | "
                      f"{tr_stats['n']} / {tr_stats['hit']*100 if not np.isnan(tr_stats['hit']) else 0:.1f}% / "
                      f"{tr_stats['roi']:+.2f}% | "
                      f"{hd_stats['n']} / {hd_stats['hit']*100 if not np.isnan(hd_stats['hit']) else 0:.1f}% / "
                      f"{hd_stats['roi']:+.2f}% / [{hd_stats['ci_lo']:+.0f}, {hd_stats['ci_hi']:+.0f}] | "
                      f"{d_hit:+.1f}pp | {verdict} |")

            # Compare S2 vs own_q10 on holdout
            if hd_stats["n"] > 0 and hd_own_stats["n"] > 0:
                lift = hd_stats["roi"] - hd_own_stats["roi"]
                holdout_lifts.append({"asset": asset, "tf": tf, "lift_pp": lift,
                                      "s2_n": hd_stats["n"], "own_n": hd_own_stats["n"]})
                rows_csv.append({"phase": "holdout", "asset": asset, "tf": tf,
                                 "s2_n": hd_stats["n"], "s2_hit": hd_stats["hit"], "s2_roi": hd_stats["roi"],
                                 "own_n": hd_own_stats["n"], "own_roi": hd_own_stats["roi"],
                                 "lift_pp": lift})

    md.append("\n## Holdout: S2 vs own_q10 head-to-head\n")
    md.append("| TF | Asset | S2 holdout n / ROI | own_q10 holdout n / ROI | Lift |")
    md.append("|---|---|---|---|---|")
    for hl in holdout_lifts:
        md.append(f"| {hl['tf']} | {hl['asset']} | {hl['s2_n']} / ? | "
                  f"{hl['own_n']} / ? | **{hl['lift_pp']:+.2f}pp** |")

    # Verdict
    md.append("\n## Verdict\n")
    n_holdout_positive = sum(1 for hl in holdout_lifts if hl["lift_pp"] > 0)
    n_total = len(holdout_lifts)
    md.append(f"- In-sample lift over own_q10: see top table")
    md.append(f"- Day-by-day lift: {days_lift}/{df_s2.date.nunique()} days")
    md.append(f"- Holdout lift positive in: **{n_holdout_positive}/{n_total} cells**")
    if n_holdout_positive >= 3 and days_lift >= 4:
        md.append(f"\n✅ **Cross-asset filter (S2) generalizes.** Worth deploying as ETH/SOL-specific signal augmentation.")
    elif n_holdout_positive >= 2:
        md.append(f"\n⚠️ **Mixed.** Forward-walk shows partial generalization. Pilot with caution.")
    else:
        md.append(f"\n❌ **Edge does not survive holdout.** In-sample lift was likely artifact.")

    pd.DataFrame(rows_csv).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")
    print(f"\nDay lift: {days_lift}/{df_s2.date.nunique()}, Holdout cells positive: {n_holdout_positive}/{n_total}")


if __name__ == "__main__":
    main()
