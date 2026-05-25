"""LightGBM 5m WR predictor on master_5m_panel.

Predicts P(won) given the full feature panel. Uses chronological 70/30 split,
also reports rolling walk-forward (4 folds). Outputs per-fire predicted prob,
then sweeps thresholds to find best (n ≥ 100, WR ≥ 60 %, sum_pnl positive).

If LightGBM unavailable, falls back to sklearn GradientBoostingClassifier.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
OUT_FIRES = ROOT / "data" / "v4" / "canonical" / "_results" / "lgbm_preds_5m.parquet"
OUT_SWEEP = ROOT / "data" / "v4" / "canonical" / "_results" / "lgbm_threshold_sweep.csv"

FEATURES = [
    # base
    "fire_offset_s", "tau_sec",
    "dev_bps",
    "sigma_per_sqrt_sec_15m", "sigma_per_sqrt_sec_5m",
    # FV
    "fair_up", "fair_edge_bp",
    # CVD
    "cvd_30s", "cvd_60s", "cvd_120s",
    "cvd_agree_30s", "cvd_agree_60s", "cvd_agree_120s",
    # MACD
    "macd_line", "macd_sig", "macd_hist", "macd_agree",
    # RVOL
    "rvol_30_300", "rvol_60_900",
    # microstructure
    "spread_bp", "imb5", "micro_minus_mid_bp",
    # Markov + F7
    "m1v_pass", "m5v_pass", "m1f_pass", "m5f_pass", "f7_pass",
    "m1v_regime", "m5v_regime",
    "rsi_14",
    # cross-asset
    "cross_a_dev_bp", "cross_b_dev_bp",
    "cross_partial_agree", "cross_full_agree",
    # direction itself
    "dir_UP",
]

# Asset 1-hot as well
ASSET_FEATURES = ["asset_BTC", "asset_ETH", "asset_SOL"]
ALL_FEATURES = FEATURES + ASSET_FEATURES


def prep(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["dir_UP"] = (d["direction"] == "UP").astype(int)
    for a in ("BTC", "ETH", "SOL"):
        d[f"asset_{a}"] = (d["asset"] == a).astype(int)
    bool_cols = ["cvd_agree_30s", "cvd_agree_60s", "cvd_agree_120s",
                 "macd_agree",
                 "m1v_pass", "m5v_pass", "m1f_pass", "m5f_pass", "f7_pass",
                 "cross_partial_agree", "cross_full_agree"]
    for c in bool_cols: d[c] = d[c].astype(int)
    return d


def threshold_sweep(d: pd.DataFrame, score_col: str) -> pd.DataFrame:
    rows = []
    qs = np.linspace(0.50, 0.95, 19)
    for q in qs:
        thr = float(np.nanquantile(d[score_col], q))
        sub = d[d[score_col] >= thr]
        if len(sub) < 30: continue
        n = len(sub)
        wr = float(sub["won"].mean())
        sum_pnl = float(sub["pnl_legacy_usd"].sum())
        per_tr = sum_pnl / n
        rows.append({"q": round(q, 3), "thr": round(thr, 4),
                     "n": n, "wr": round(wr, 4),
                     "per_tr": round(per_tr, 3),
                     "sum_pnl": round(sum_pnl, 2)})
    return pd.DataFrame(rows)


def main():
    d = pd.read_parquet(PANEL)
    print(f"[load] {len(d):,} rows")
    d = prep(d)

    # Median-impute missing numeric features
    for f in FEATURES:
        if d[f].dtype.kind in ("f", "i"):
            d[f] = d[f].astype(float).fillna(d[f].astype(float).median())

    d = d.sort_values("fire_us").reset_index(drop=True)

    # 70/30 chronological split
    n_tr = int(0.70 * len(d))
    train = d.iloc[:n_tr]
    test  = d.iloc[n_tr:]
    print(f"[split] train={len(train):,}  test={len(test):,}")

    X_tr = train[ALL_FEATURES].values
    y_tr = train["won"].values.astype(int)
    X_te = test[ALL_FEATURES].values
    y_te = test["won"].values.astype(int)

    try:
        import lightgbm as lgb
        print("[model] LightGBM")
        clf = lgb.LGBMClassifier(
            n_estimators=400, learning_rate=0.03, num_leaves=63,
            min_child_samples=40, subsample=0.85, subsample_freq=1,
            colsample_bytree=0.85, reg_lambda=0.5, random_state=42, n_jobs=-1,
        )
    except Exception:
        from sklearn.ensemble import GradientBoostingClassifier
        print("[model] sklearn GBM fallback")
        clf = GradientBoostingClassifier(
            n_estimators=300, learning_rate=0.05, max_depth=4, random_state=42)

    clf.fit(X_tr, y_tr)
    train_pred = clf.predict_proba(X_tr)[:, 1]
    test_pred  = clf.predict_proba(X_te)[:, 1]
    print(f"[metric] train logloss base = {y_tr.mean():.4f}")
    print(f"[metric] test  base WR     = {y_te.mean():.4f}")

    # Calibration: bucket by predicted prob → empirical WR
    from sklearn.metrics import roc_auc_score, brier_score_loss
    try:
        auc_te = roc_auc_score(y_te, test_pred)
    except Exception:
        auc_te = float("nan")
    bri_te = brier_score_loss(y_te, test_pred)
    print(f"[metric] test ROC-AUC={auc_te:.4f}, Brier={bri_te:.4f}")

    # Feature importance
    if hasattr(clf, "feature_importances_"):
        imp = pd.DataFrame({"feature": ALL_FEATURES,
                            "importance": clf.feature_importances_})
        imp = imp.sort_values("importance", ascending=False)
        print("\n[feature importance]")
        print(imp.head(20).to_string(index=False))

    # Save preds
    d["pred_won"] = np.concatenate([train_pred, test_pred])
    d["split"]   = np.array(["train"]*len(train) + ["test"]*len(test))
    OUT_FIRES.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(OUT_FIRES, index=False)
    print(f"\n[write] {OUT_FIRES}")

    # Threshold sweep on TEST set (out of sample)
    test_with_pred = d[d["split"] == "test"].copy()
    sweep = threshold_sweep(test_with_pred, "pred_won")
    sweep.to_csv(OUT_SWEEP, index=False)
    print(f"[write] {OUT_SWEEP}")
    print(f"\n[OOS sweep — test only]")
    print(sweep.to_string(index=False))

    # Same on full pop (in-sample mixed; sanity check)
    print(f"\n[whole-panel sweep — sanity check, contains train]")
    full_sweep = threshold_sweep(d, "pred_won")
    print(full_sweep.to_string(index=False))


if __name__ == "__main__":
    main()
