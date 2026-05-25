"""LightGBM trained with SLUG-level chronological split (honest OOS).

The fire-level split leaks correlation (multiple offsets of the same slug have
the same outcome). This script splits on UNIQUE (asset, slug) pairs in time
order — first 70 % of slugs train, last 30 % test. All offsets of a given slug
go to one fold.

Then evaluates threshold sweep on OOS predictions and on a DEDUPED (one fire
per slug-direction) deployment.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
OUT_FIRES = ROOT / "data" / "v4" / "canonical" / "_results" / "lgbm_slug_split_preds.parquet"
OUT_SWEEP = ROOT / "data" / "v4" / "canonical" / "_results" / "lgbm_slug_split_sweep.csv"

FEATURES = [
    "fire_offset_s", "tau_sec",
    "dev_bps",
    "sigma_per_sqrt_sec_15m", "sigma_per_sqrt_sec_5m",
    "fair_up", "fair_edge_bp",
    "cvd_30s", "cvd_60s", "cvd_120s",
    "cvd_agree_30s", "cvd_agree_60s", "cvd_agree_120s",
    "macd_line", "macd_sig", "macd_hist", "macd_agree",
    "rvol_30_300", "rvol_60_900",
    "spread_bp", "imb5", "micro_minus_mid_bp",
    "m1v_pass", "m5v_pass", "m1f_pass", "m5f_pass", "f7_pass",
    "m1v_regime", "m5v_regime",
    "rsi_14",
    "cross_a_dev_bp", "cross_b_dev_bp",
    "cross_partial_agree", "cross_full_agree",
    "dir_UP",
    "asset_BTC", "asset_ETH", "asset_SOL",
]


def prep(d):
    d = d.copy()
    d["dir_UP"] = (d["direction"] == "UP").astype(int)
    for a in ("BTC", "ETH", "SOL"):
        d[f"asset_{a}"] = (d["asset"] == a).astype(int)
    bools = ["cvd_agree_30s","cvd_agree_60s","cvd_agree_120s","macd_agree",
             "m1v_pass","m5v_pass","m1f_pass","m5f_pass","f7_pass",
             "cross_partial_agree","cross_full_agree"]
    for c in bools: d[c] = d[c].astype(int)
    return d


def threshold_sweep(d: pd.DataFrame, col: str) -> pd.DataFrame:
    qs = np.linspace(0.50, 0.95, 19)
    rows = []
    for q in qs:
        thr = float(np.nanquantile(d[col], q))
        sub = d[d[col] >= thr]
        if len(sub) < 30: continue
        wr = float(sub["won"].mean())
        sum_pnl = float(sub["pnl_legacy_usd"].sum())
        per_tr = sum_pnl / len(sub)
        rows.append({"q": round(q, 3), "thr": round(thr, 4),
                     "n": len(sub), "wr_pct": round(wr*100, 2),
                     "per_tr": round(per_tr, 3),
                     "sum_pnl": round(sum_pnl, 2)})
    return pd.DataFrame(rows)


def main():
    d = pd.read_parquet(PANEL)
    print(f"[load] {len(d):,} rows")
    d = prep(d)
    for f in FEATURES:
        if d[f].dtype.kind in ("f", "i"):
            d[f] = d[f].astype(float).fillna(d[f].astype(float).median())

    # SLUG-level chronological split
    slug_first_us = (d.groupby(["asset", "slug"])["fire_us"].min()
                       .reset_index().sort_values("fire_us"))
    n_total = len(slug_first_us)
    cut = int(0.70 * n_total)
    train_slugs = set(zip(slug_first_us["asset"].iloc[:cut],
                          slug_first_us["slug"].iloc[:cut]))
    test_slugs  = set(zip(slug_first_us["asset"].iloc[cut:],
                          slug_first_us["slug"].iloc[cut:]))
    d["split"] = np.where([(a, s) in train_slugs
                           for a, s in zip(d["asset"], d["slug"])],
                          "train", "test")
    train = d[d["split"] == "train"]
    test  = d[d["split"] == "test"]
    print(f"[split] train slugs={cut} ({len(train):,} fires)  "
          f"test slugs={n_total-cut} ({len(test):,} fires)")
    print(f"[base] train WR={train['won'].mean():.4f}  test WR={test['won'].mean():.4f}")

    X_tr = train[FEATURES].values; y_tr = train["won"].astype(int).values
    X_te = test [FEATURES].values; y_te = test ["won"].astype(int).values

    import lightgbm as lgb
    clf = lgb.LGBMClassifier(
        n_estimators=500, learning_rate=0.03, num_leaves=63,
        min_child_samples=40, subsample=0.85, subsample_freq=1,
        colsample_bytree=0.85, reg_lambda=0.5, random_state=42, n_jobs=-1,
        verbose=-1,
    )
    clf.fit(X_tr, y_tr)
    p_tr = clf.predict_proba(X_tr)[:, 1]
    p_te = clf.predict_proba(X_te)[:, 1]

    from sklearn.metrics import roc_auc_score, brier_score_loss
    try:
        auc_te = float(roc_auc_score(y_te, p_te))
    except Exception:
        auc_te = float("nan")
    bri_te = float(brier_score_loss(y_te, p_te))
    print(f"[metric] OOS ROC-AUC={auc_te:.4f}  Brier={bri_te:.4f}")

    if hasattr(clf, "feature_importances_"):
        imp = pd.DataFrame({"feature": FEATURES,
                            "importance": clf.feature_importances_})
        imp = imp.sort_values("importance", ascending=False)
        print("\n[feature importance]")
        print(imp.head(15).to_string(index=False))

    # Stitch predictions
    d.loc[d["split"] == "train", "pred_won"] = p_tr
    d.loc[d["split"] == "test",  "pred_won"] = p_te
    OUT_FIRES.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(OUT_FIRES, index=False)
    print(f"\n[write] {OUT_FIRES}")

    # Sweep on OOS only — fire-level
    print(f"\n[OOS sweep — fire level]")
    sw = threshold_sweep(d[d["split"] == "test"], "pred_won")
    sw.to_csv(OUT_SWEEP, index=False)
    print(sw.to_string(index=False))

    # SWEEP DEDUPED — one fire per (slug, direction) where pred_won is max
    print(f"\n[OOS sweep — DEDUPED to one fire per (slug, direction), max pred]")
    test = d[d["split"] == "test"].copy()
    # for each (slug, direction): the offset with max pred_won
    idx = (test.sort_values("pred_won", ascending=False)
                .drop_duplicates(["asset", "slug", "direction"], keep="first")
                .index)
    dedup_test = test.loc[idx]
    print(f"  deduped n: {len(dedup_test):,} (from {len(test):,} fires)")
    sw_dedup = threshold_sweep(dedup_test, "pred_won")
    print(sw_dedup.to_string(index=False))
    sw_dedup.to_csv(str(OUT_SWEEP).replace(".csv", "_dedup.csv"), index=False)


if __name__ == "__main__":
    main()
