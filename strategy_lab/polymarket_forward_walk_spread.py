"""
polymarket_forward_walk_spread.py — forward-walk validation for spread<2% filter from E4.

Best E4 variant in-sample: spread_lt_2pct → ROI +30.69% (lift +4.54pp), n=180.
Test: chronological 80/20 split per (asset, tf). q10 quantile fit on TRAIN only.
Spread filter (<2%) applied to BOTH train and holdout.
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
SPREAD_THRESHOLD = 2.0  # %

OUT_MD = HERE / "reports" / "POLYMARKET_FORWARD_WALK_SPREAD.md"
OUT_CSV = HERE / "results" / "polymarket" / "forward_walk_spread.csv"


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


def load_book_depth(asset):
    df = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_book_depth_v3.csv")
    cols_ask_p = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_ask_s = [f"ask_size_{i}" for i in range(LEVELS)]
    cols_bid_p = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bid_s = [f"bid_size_{i}" for i in range(LEVELS)]
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
        out.setdefault(slugs[i], {})[outcomes[i]] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


def compute_spread_pct(row, book_by_asset):
    sig = int(row.signal)
    held = "Up" if sig == 1 else "Down"
    book = book_by_asset[row.asset].get(row.slug, {}).get(held)
    if book is None:
        return float("nan")
    ask_p, ask_s, bid_p, bid_s = book
    a0 = ask_p[0] if np.isfinite(ask_p[0]) else float("nan")
    b0 = bid_p[0] if np.isfinite(bid_p[0]) else float("nan")
    if not (np.isfinite(a0) and np.isfinite(b0)):
        return float("nan")
    mid = (a0 + b0) / 2
    if mid <= 0:
        return float("nan")
    return (a0 - b0) / mid * 100


def evaluate(df, traj, k1m, rev_bp=REV_BP):
    pnls = []
    for _, row in df.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        p = simulate_market(row, traj_g, k1m[row.asset],
                            target=None, stop=None, rev_bp=rev_bp,
                            merge_aware=False, hedge_hold=True)
        if p is not None and np.isfinite(p):
            pnls.append(p)
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"), "ci_lo": 0, "ci_hi": 0}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
    }


def main():
    print(f"Loading... (rev_bp={REV_BP}, spread<{SPREAD_THRESHOLD}%)")
    feats_by_asset = {a: load_features(a) for a in ASSETS}
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    k1m_by_asset = {a: load_klines_1m(a) for a in ASSETS}
    book_by_asset = {a: load_book_depth(a) for a in ASSETS}

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

            # Compute spread
            train_signal["spread_pct"] = train_signal.apply(
                lambda r: compute_spread_pct(r, book_by_asset), axis=1)
            holdout_signal["spread_pct"] = holdout_signal.apply(
                lambda r: compute_spread_pct(r, book_by_asset), axis=1)

            # No-filter: just q10 + simulator
            tr_no = evaluate(train_signal.dropna(subset=["spread_pct"]), traj_by_asset, k1m_by_asset)
            hd_no = evaluate(holdout_signal.dropna(subset=["spread_pct"]), traj_by_asset, k1m_by_asset)

            # With spread filter <2%
            tr_filt = train_signal[train_signal.spread_pct < SPREAD_THRESHOLD]
            hd_filt = holdout_signal[holdout_signal.spread_pct < SPREAD_THRESHOLD]
            tr_f = evaluate(tr_filt, traj_by_asset, k1m_by_asset)
            hd_f = evaluate(hd_filt, traj_by_asset, k1m_by_asset)

            row = {
                "tf": tf, "asset": asset_filter or "ALL",
                "tr_no_n": tr_no["n"], "tr_no_roi": tr_no["roi"],
                "hd_no_n": hd_no["n"], "hd_no_roi": hd_no["roi"], "hd_no_hit": hd_no["hit"],
                "hd_no_ci_lo": hd_no["ci_lo"], "hd_no_ci_hi": hd_no["ci_hi"],
                "tr_f_n": tr_f["n"], "tr_f_roi": tr_f["roi"],
                "hd_f_n": hd_f["n"], "hd_f_roi": hd_f["roi"], "hd_f_hit": hd_f["hit"],
                "hd_f_ci_lo": hd_f["ci_lo"], "hd_f_ci_hi": hd_f["ci_hi"],
                "hd_lift_pp": hd_f["roi"] - hd_no["roi"] if not (np.isnan(hd_f["roi"]) or np.isnan(hd_no["roi"])) else float("nan"),
            }
            rows.append(row)
            print(f"{tf:3s} {(asset_filter or 'ALL'):3s}: "
                  f"TRAIN no_filt n={tr_no['n']:>3d} ROI={tr_no['roi']:+.2f}% | "
                  f"with_filt n={tr_f['n']:>3d} ROI={tr_f['roi']:+.2f}% | "
                  f"HOLDOUT no_filt n={hd_no['n']:>3d} ROI={hd_no['roi']:+.2f}% | "
                  f"with_filt n={hd_f['n']:>3d} ROI={hd_f['roi']:+.2f}% lift={row['hd_lift_pp']:+.2f}pp")

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    md = ["# Forward-Walk: Spread Filter (<2%) for q10 hedge-hold strategy\n",
          f"Per (asset, tf): chronological 80/20 split. q10 quantile fit on TRAIN only. "
          f"Spread filter applied to both TRAIN and HOLDOUT identically.\n",
          "\n## Holdout: no-filter vs spread<2%\n",
          "| TF | Asset | Holdout no-filt n / ROI | Holdout w/filter n / hit / ROI / 95% CI | Holdout lift |",
          "|---|---|---|---|---|"]
    holdout_lifts = []
    for r in rows:
        md.append(f"| {r['tf']} | {r['asset']} | "
                  f"{r['hd_no_n']} / {r['hd_no_roi']:+.2f}% | "
                  f"{r['hd_f_n']} / {r['hd_f_hit']*100 if not np.isnan(r['hd_f_hit']) else 0:.1f}% / "
                  f"{r['hd_f_roi']:+.2f}% / [{r['hd_f_ci_lo']:+.0f}, {r['hd_f_ci_hi']:+.0f}] | "
                  f"**{r['hd_lift_pp']:+.2f}pp** |")
        holdout_lifts.append(r["hd_lift_pp"])

    n_positive = sum(1 for h in holdout_lifts if not np.isnan(h) and h > 0)
    n_total = sum(1 for h in holdout_lifts if not np.isnan(h))
    md.append(f"\n## Summary\n")
    md.append(f"Holdout lift positive: **{n_positive} / {n_total} cells**")
    if n_positive / max(n_total, 1) >= 0.6:
        md.append("\n✅ **Spread filter generalizes.** Worth deploying as additional gate on q10/q20 hedge-hold.")
    elif n_positive / max(n_total, 1) >= 0.4:
        md.append("\n⚠️ **Borderline.** Some holdout cells positive, others negative. Pilot with caution.")
    else:
        md.append("\n❌ **Edge does not generalize.**")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")
    print(f"Holdout lift positive: {n_positive}/{n_total}")


if __name__ == "__main__":
    main()
