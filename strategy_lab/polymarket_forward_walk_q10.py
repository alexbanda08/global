"""
polymarket_forward_walk_q10.py — Out-of-sample test for q10 vs q20 (locked baseline).

Same framework as polymarket_forward_walk_v2.py:
  - chronological 80/20 split per (asset, timeframe)
  - quantile threshold (q20=80th, q10=90th) fit on TRAIN ONLY
  - applied to both train and holdout
  - hedge-hold rev_bp=5 (LOCKED baseline exit)

Reports train vs holdout side-by-side. If holdout hit% stays within ~5pp of train
AND CI lower bound > 0, the q10 edge generalizes.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import (
    load_features, load_trajectories, load_klines_1m,
    simulate_market,
)

OUT_MD = HERE / "reports" / "POLYMARKET_FORWARD_WALK_Q10.md"
OUT_CSV = HERE / "results" / "polymarket" / "forward_walk_q10.csv"
RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5  # locked baseline


def split_chrono(df, train_frac=0.8):
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    cut = int(len(df) * train_frac)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def evaluate(df, traj_by_asset, k1m_by_asset, rev_bp, hedge_hold=True):
    pnls = []
    for _, row in df.iterrows():
        traj_g = traj_by_asset[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        k1m = k1m_by_asset[row.asset]
        pnls.append(simulate_market(row, traj_g, k1m,
                                    target=None, stop=None,
                                    rev_bp=rev_bp, merge_aware=False,
                                    hedge_hold=hedge_hold))
    pnls = np.array(pnls)
    if len(pnls) == 0:
        return {"n":0,"total_pnl":0.0,"ci_lo":0.0,"ci_hi":0.0,"hit":float("nan"),"roi":float("nan"),"pnl_mean":0.0}
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    return {
        "n": len(pnls),
        "total_pnl": float(pnls.sum()),
        "pnl_mean": float(pnls.mean()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
    }


def add_quantile_signal_with_train_threshold(df, train_df, quantile=0.80):
    """Compute |ret_5m| quantile threshold per (asset, tf) from train_df only, apply to df."""
    out = df.copy()
    out["signal"] = -1
    for asset in out.asset.unique():
        for tf in out.timeframe.unique():
            train_sub = train_df[(train_df.asset == asset) & (train_df.timeframe == tf)]
            ret_train = train_sub.ret_5m.abs().dropna()
            if len(ret_train) < 5:
                continue
            thr = ret_train.quantile(quantile)
            sel = ((out.asset == asset) & (out.timeframe == tf) &
                   out.ret_5m.notna() & (out.ret_5m.abs() >= thr))
            out.loc[sel, "signal"] = (out.loc[sel, "ret_5m"] > 0).astype(int)
    return out[out.signal != -1].copy()


def main():
    print(f"Loading data... (rev_bp={REV_BP}, hedge-hold)")
    feats_by_asset = {a: load_features(a) for a in ASSETS}
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    k1m_by_asset = {a: load_klines_1m(a) for a in ASSETS}

    rows = []
    SIGNALS = [("q20", 0.80), ("q10", 0.90)]

    for sig_label, q in SIGNALS:
        for tf in ["5m", "15m"]:
            for asset_filter in [None, "btc", "eth", "sol"]:
                # Combine into one df with asset filter
                if asset_filter:
                    raw = feats_by_asset[asset_filter]
                    raw = raw[raw.timeframe == tf].copy()
                else:
                    raw = pd.concat([feats_by_asset[a][feats_by_asset[a].timeframe == tf]
                                     for a in ASSETS], ignore_index=True)
                if len(raw) < 50:
                    continue
                train_raw, holdout_raw = split_chrono(raw, train_frac=0.8)
                train_signal = add_quantile_signal_with_train_threshold(train_raw, train_raw, quantile=q)
                holdout_signal = add_quantile_signal_with_train_threshold(holdout_raw, train_raw, quantile=q)

                tr = evaluate(train_signal, traj_by_asset, k1m_by_asset, REV_BP)
                hd = evaluate(holdout_signal, traj_by_asset, k1m_by_asset, REV_BP)

                row = {
                    "signal": sig_label,
                    "tf": tf,
                    "asset": asset_filter or "ALL",
                    "train_n": tr["n"], "train_hit": tr["hit"], "train_roi": tr["roi"],
                    "train_pnl": tr["total_pnl"], "train_ci_lo": tr["ci_lo"], "train_ci_hi": tr["ci_hi"],
                    "holdout_n": hd["n"], "holdout_hit": hd["hit"], "holdout_roi": hd["roi"],
                    "holdout_pnl": hd["total_pnl"], "holdout_ci_lo": hd["ci_lo"], "holdout_ci_hi": hd["ci_hi"],
                    "hit_drop": (tr["hit"] - hd["hit"]) * 100 if not np.isnan(hd["hit"]) else float("nan"),
                }
                rows.append(row)
                print(f"{sig_label:3s} {tf:3s} {(asset_filter or 'ALL'):3s}: "
                      f"TRAIN n={tr['n']:>3d} hit={tr['hit']*100:5.1f}% ROI={tr['roi']:+6.2f}% | "
                      f"HOLDOUT n={hd['n']:>3d} hit={hd['hit']*100 if not np.isnan(hd['hit']) else 0:5.1f}% "
                      f"ROI={hd['roi']:+6.2f}% [{hd['ci_lo']:+.0f},{hd['ci_hi']:+.0f}] "
                      f"Δhit={(tr['hit']-hd['hit'])*100 if not np.isnan(hd['hit']) else 0:+5.1f}pp")

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    md = ["# Forward-Walk Holdout — q10 vs q20 (locked baseline)\n",
          f"Per (asset, timeframe, signal): chronological 80/20 split. Quantile threshold "
          f"fit on TRAIN only, applied to both. Strategy = sig_ret5m + hedge-hold rev_bp={REV_BP}.\n",
          "\n**Verdict criteria:** holdout hit within ±5pp of train AND holdout CI > 0 → edge generalizes.\n"]

    for sig_label in ["q20", "q10"]:
        md.append(f"\n## {sig_label} signal\n")
        md.append("| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Δhit | Verdict |")
        md.append("|---|---|---|---|---|---|")
        sub = [r for r in rows if r["signal"] == sig_label]
        for r in sub:
            verdict = ""
            if r["holdout_n"] == 0 or np.isnan(r["holdout_hit"]):
                verdict = "—"
            else:
                hit_ok = abs(r["hit_drop"]) <= 5
                ci_ok = r["holdout_ci_lo"] > 0
                if hit_ok and ci_ok:
                    verdict = "✅ generalizes"
                elif ci_ok:
                    verdict = "⚠️ CI ok but hit drift"
                elif hit_ok:
                    verdict = "⚠️ hit ok but CI overlaps zero"
                else:
                    verdict = "❌ does not generalize"
            md.append(f"| {r['tf']} | {r['asset']} | "
                      f"{r['train_n']} / {r['train_hit']*100:.1f}% / {r['train_roi']:+.2f}% | "
                      f"{r['holdout_n']} / {r['holdout_hit']*100 if not np.isnan(r['holdout_hit']) else 0:.1f}% / "
                      f"{r['holdout_roi']:+.2f}% / [{r['holdout_ci_lo']:+.0f}, {r['holdout_ci_hi']:+.0f}] | "
                      f"{r['hit_drop']:+.1f}pp | {verdict} |")

    md.append("\n## q10 vs q20 head-to-head (HOLDOUT only)\n")
    md.append("| TF | Asset | q20 holdout ROI | q10 holdout ROI | Δ | q20 holdout hit | q10 holdout hit | Δ |")
    md.append("|---|---|---|---|---|---|---|---|")
    for tf in ["5m", "15m"]:
        for asset in ["ALL", "btc", "eth", "sol"]:
            r20 = next((r for r in rows if r["signal"]=="q20" and r["tf"]==tf and r["asset"]==asset), None)
            r10 = next((r for r in rows if r["signal"]=="q10" and r["tf"]==tf and r["asset"]==asset), None)
            if not r20 or not r10:
                continue
            d_roi = r10["holdout_roi"] - r20["holdout_roi"]
            d_hit = (r10["holdout_hit"] - r20["holdout_hit"]) * 100
            arrow = "✅" if d_roi > 0 else "❌"
            md.append(f"| {tf} | {asset} | {r20['holdout_roi']:+.2f}% | {r10['holdout_roi']:+.2f}% | "
                      f"{d_roi:+.2f}pp {arrow} | {r20['holdout_hit']*100:.1f}% | "
                      f"{r10['holdout_hit']*100:.1f}% | {d_hit:+.1f}pp |")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
